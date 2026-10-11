"""Time-weighted, causal features from Step 4/5 CSV; standard library only."""
import bisect
import csv
import json
import math
from pathlib import Path


def number(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def yes(value):
    return str(value) in ('1', 'True', 'true')


def weighted_stats(samples):
    """Inverse weighted CDF p10; each value held over its observed interval."""
    total = sum(w for _, w in samples)
    if not total:
        return dict(mean=None, std=None, p10=None)
    mean = sum(v*w for v,w in samples)/total
    variance = sum(w*(v-mean)**2 for v,w in samples)/total
    cumulative = 0.
    for value, weight in sorted(samples):
        cumulative += weight
        if cumulative >= .1*total:
            return dict(mean=mean, std=math.sqrt(max(0.,variance)), p10=value)


def with_baselines(rows, calibrations):
    """Attach ONLY preceding completed calibration; never infer from tracking."""
    completions = [number(c.get('completed_at_s')) for c in calibrations]
    if any(t is None for t in completions) or any(b<=a for a,b in zip(completions,completions[1:])):
        raise ValueError('Calibration completion times must be finite and increasing')
    for c in calibrations:
        if any(number(c.get('baseline',{}).get(side+'_baseline')) is None or
               float(c['baseline'][side+'_baseline'])<=0 for side in ('left','right')):
            raise ValueError('Calibration EAR baselines must be finite and positive')
    result=[]
    for row in rows:
        r=dict(row)
        t=number(r.get('t_seconds'))
        if t is None: raise ValueError('Invalid frame timestamp')
        i=bisect.bisect_right(completions,t)-1
        if r.get('phase')=='TRACKING' and i>=0:
            for side in ('left','right'):
                key=side+'_ear_baseline'
                baseline=calibrations[i]['baseline'][side+'_baseline']
                existing=number(r.get(key))
                if existing is not None and not math.isclose(existing,float(baseline),rel_tol=1e-4,abs_tol=1e-6):
                    raise ValueError('Frame baseline differs from supplied report')
                r[key]=baseline
        result.append(r)
    return result


class ObservedClosed:
    """Strict uninterrupted CLOSED observations, including unknown onset."""
    def __init__(self, threshold=1.5, max_gap=.2):
        self.threshold, self.max_gap = threshold, max_gap
        self.start = self.last = None
        self.unknown_onset = False
        self.sent = False

    def update(self, t, state, known_duration):
        if self.last is not None and (t <= self.last or t-self.last > self.max_gap):
            self.start = None
            self.sent = False
        if state != 'CLOSED':
            self.start = None
            self.sent = False
        elif self.start is None:
            self.start = t
            self.unknown_onset = known_duration is None
        duration = None if self.start is None else t-self.start
        event = None
        if duration is not None and duration >= self.threshold and not self.sent:
            self.sent = True
            if self.unknown_onset:
                event = dict(channel='eyes', kind='observed_long_closure_flag',
                             start_s=self.start, end_s=t, duration_s=duration,
                             start_known=0, peak=None, reason='observed_lower_bound_threshold')
        self.last = t
        return duration, self.sent and state == 'CLOSED', event


def validate_config(window, stride, max_gap, min_valid):
    if not all(math.isfinite(x) and x > 0 for x in (window, stride, max_gap)):
        raise ValueError('window, stride, max-gap must be finite and > 0')
    if not math.isfinite(min_valid) or not 0 <= min_valid <= 1:
        raise ValueError('min-valid must be between 0 and 1')


def aggregate(rows, events, window=30., stride=5., max_gap=.2, min_valid=.8):
    """Half-open windows [start,end); only events available strictly before end.

    Interval valid only when BOTH endpoints are valid TRACKING in the same
    calibration segment and gap <= max_gap. No interpolation over missing data.
    Rates are counts/valid channel minutes. Completed durations count by
    availability, so they may start outside the window; explicit field names.
    """
    validate_config(window, stride, max_gap, min_valid)
    times = [number(r.get('t_seconds')) for r in rows]
    if any(t is None for t in times) or any(b <= a for a,b in zip(times,times[1:])):
        raise ValueError('Frame timestamps must be finite and strictly increasing')
    segments = []
    active = None
    for i,r in enumerate(rows):
        if r.get('phase') == 'TRACKING':
            if active is None:
                active = i
        elif active is not None:
            segments.append((active, i-1)); active = None
    if active is not None:
        segments.append((active, len(rows)-1))
    evs = []
    for e in events:
        end = number(e.get('end_s'))
        available = number(e.get('available_at_s'))
        if end is None:
            raise ValueError('Event end_s must be finite')
        available = end if available is None else available
        if available < end-1e-6:
            raise ValueError('Event cannot be available before its end')
        evs.append((available,e))
    evs.sort(key=lambda x:x[0]); event_times=[x[0] for x in evs]
    output=[]
    for segment_id,(first,last) in enumerate(segments):
        anchor=times[first]
        k=0
        while anchor+window+k*stride <= times[last]+1e-8:
            end=anchor+window+k*stride; start=end-window; k+=1
            sums=dict(eyes_valid_s=0., mouth_valid_s=0., head_valid_s=0.,
                      eyes_closed_s=0., mouth_open_s=0., head_down_s=0.,
                      eyes_closed_mouth_open_s=0., joint_eyes_mouth_valid_s=0.,
                      eyes_closed_without_mouth_open_s=0.)
            pw=p1=p2=0.; longest=run=0.
            ear_samples={key:[] for key in ('left_ear','right_ear','left_ear_norm','right_ear_norm','bilateral_ear_norm')}
            ear_valid_s=ear_norm_valid_s=ear_difference=0.
            lo=max(first,bisect.bisect_right(times,start)-1)
            hi=min(last,bisect.bisect_right(times,end)-1)
            for i in range(lo,hi):
                a,b=rows[i],rows[i+1]; dt=times[i+1]-times[i]
                weight=max(0., min(end,times[i+1])-max(start,times[i]))
                if not weight: continue
                ok=dt<=max_gap
                # Continuous geometry remains useful during valid eye disagreement.
                continuous=ok and all(yes(r.get('eyes_valid')) and
                    all(number(r.get(side+'_ear')) is not None and float(r[side+'_ear'])>=0
                        for side in ('left','right')) for r in (a,b))
                if continuous:
                    ear_valid_s+=weight
                    for side in ('left','right'):
                        ear_samples[side+'_ear'].append((float(a[side+'_ear']),weight))
                    normalized=all(number(r.get(side+'_ear_baseline')) is not None and
                        float(r[side+'_ear_baseline'])>0 for r in (a,b) for side in ('left','right'))
                    normalized=normalized and all(math.isclose(float(a[side+'_ear_baseline']),
                        float(b[side+'_ear_baseline']),rel_tol=1e-6,abs_tol=1e-8) for side in ('left','right'))
                    if normalized:
                        left=float(a['left_ear'])/float(a['left_ear_baseline'])
                        right=float(a['right_ear'])/float(a['right_ear_baseline'])
                        ear_samples['left_ear_norm'].append((left,weight))
                        ear_samples['right_ear_norm'].append((right,weight))
                        ear_samples['bilateral_ear_norm'].append(((left+right)/2,weight))
                        ear_difference+=abs(left-right)*weight
                        ear_norm_valid_s+=weight
                eye=ok and all(yes(r.get('eyes_valid')) and r.get('eye_state') in ('OPEN','CLOSED') for r in (a,b))
                mouth=ok and all(yes(r.get('mouth_valid')) and r.get('mouth_state') in ('OPEN','CLOSED') for r in (a,b))
                head=ok and all(yes(r.get('pose_valid')) and r.get('head_state') in ('NEUTRAL','DOWN') for r in (a,b))
                closed=eye and a['eye_state']==b['eye_state']=='CLOSED'
                opened=mouth and a['mouth_state']==b['mouth_state']=='OPEN'
                down=head and a['head_state']==b['head_state']=='DOWN'
                for key,flag in [('eyes_valid_s',eye),('mouth_valid_s',mouth),('head_valid_s',head),
                                 ('eyes_closed_s',closed),('mouth_open_s',opened),('head_down_s',down),
                                 ('joint_eyes_mouth_valid_s',eye and mouth),
                                 ('eyes_closed_mouth_open_s',closed and opened),
                                 ('eyes_closed_without_mouth_open_s',closed and mouth and a['mouth_state']==b['mouth_state']=='CLOSED')]:
                    sums[key]+=weight*bool(flag)
                run=run+weight if closed else 0.; longest=max(longest,run)
                pitch=number(a.get('pitch_deg'))
                if head and pitch is not None and number(b.get('pitch_deg')) is not None:
                    pw+=weight; p1+=weight*pitch; p2+=weight*pitch*pitch
            result=dict(segment_id=segment_id,window_start_s=start,window_end_s=end,window_s=window,**sums)
            for channel in ('eyes','mouth','head'):
                valid=sums[channel+'_valid_s'];result[channel+'_valid_ratio']=valid/window
                result[channel+'_usable']=int(valid/window+1e-9>=min_valid and valid>0)
            ratio=lambda n,d: n/d if d>0 else None
            result.update(eyes_closed_ratio=ratio(sums['eyes_closed_s'],sums['eyes_valid_s']),
                          mouth_open_ratio=ratio(sums['mouth_open_s'],sums['mouth_valid_s']),
                          head_down_ratio=ratio(sums['head_down_s'],sums['head_valid_s']),
                          longest_observed_closed_s=longest,
                          pitch_mean_deg=ratio(p1,pw),
                          pitch_std_deg=math.sqrt(max(0.,p2/pw-(p1/pw)**2)) if pw else None)
            selected=[e for available,e in evs[bisect.bisect_left(event_times,start):bisect.bisect_left(event_times,end)]
                      if number(e.get('start_s')) is not None and float(e['start_s'])>=anchor]
            for kind,channel in [('blink_candidate','eyes'),('yawn_candidate','mouth'),('nod_candidate','head')]:
                result[kind+'_count']=sum(e.get('kind')==kind for e in selected)
                result[kind+'_per_valid_min']=ratio(result[kind+'_count']*60,sums[channel+'_valid_s'])
            durations=[number(e.get('duration_s')) for e in selected if e.get('channel')=='eyes'
                       and e.get('kind') in ('blink_candidate','brief_closure','prolonged_closure') and yes(e.get('start_known'))]
            durations=[d for d in durations if d is not None]
            result['completed_eye_duration_mean_s']=sum(durations)/len(durations) if durations else None
            result['completed_eye_duration_max_s']=max(durations) if durations else None
            result['completed_eye_closure_count']=len(durations)
            result['interrupted_event_count']=sum(str(e.get('kind','')).startswith('interrupted') for e in selected)
            result['all_channels_usable']=int(all(result[c+'_usable'] for c in ('eyes','mouth','head')))
            for key,samples in ear_samples.items():
                for stat,value in weighted_stats(samples).items():
                    result[key+'_'+stat]=value
            result.update(ear_valid_s=ear_valid_s,ear_valid_ratio=ear_valid_s/window,
                          ear_norm_valid_s=ear_norm_valid_s,ear_norm_valid_ratio=ear_norm_valid_s/window,
                          ear_norm_absdiff_mean=ratio(ear_difference,ear_norm_valid_s),
                          ear_norm_usable=int(ear_norm_valid_s>0 and ear_norm_valid_s/window+1e-9>=min_valid))
            result['model_input_usable']=int(result['all_channels_usable'] and result['ear_norm_usable'])
            result.update(subject_id='',video_id='',label='')
            output.append(result)
    return output


def export(frames_path, events_path, output_path=None, report_path=None, calibrations=None, **options):
    frames_path,events_path=Path(frames_path),Path(events_path)
    with frames_path.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    with events_path.open(encoding='utf-8-sig',newline='') as f: events=list(csv.DictReader(f))
    if report_path is not None:
        if calibrations is not None:raise ValueError('Use report_path OR calibrations')
        report=json.loads(Path(report_path).read_text(encoding='utf-8-sig'))
        for key,path in [('frames',frames_path),('events',events_path)]:
            if report.get('files',{}).get(key)!=path.name:
                raise ValueError('Report must refer to these exact frame/event filenames')
        calibrations=report.get('calibrations',[])
    if calibrations is not None:rows=with_baselines(rows,calibrations)
    required={'t_seconds','phase','eyes_valid','eye_state','mouth_valid','mouth_state','pose_valid','head_state','pitch_deg'}
    if not rows or not required.issubset(rows[0]): raise ValueError('Missing required Step 4 frame columns or empty file')
    features=aggregate(rows,events,**options)
    output_path=Path(output_path) if output_path else frames_path.with_name(frames_path.name.replace('_frames.csv','_windows.csv'))
    if output_path.resolve() in (frames_path.resolve(),events_path.resolve()):raise ValueError('Output must differ from input')
    output_path.parent.mkdir(parents=True,exist_ok=True)
    if not features: raise ValueError('No full TRACKING window; use a longer recording or smaller --window')
    with output_path.open('x',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(features[0]));w.writeheader();w.writerows(features)
    meta=dict(schema_version=2,frames_file=frames_path.name,events_file=events_path.name,
              normalization_source='report_calibrations' if report_path is not None else
                  'processor_calibrations' if calibrations is not None else 'frame_baselines_or_missing',
              report_file=Path(report_path).name if report_path is not None else None,
              normalized_ear_window_count=sum(r['ear_norm_valid_s']>0 for r in features),
              model_input_usable_count=sum(r['model_input_usable'] for r in features),
              window_count=len(features),options={**dict(window=30.,stride=5.,max_gap=.2,min_valid=.8),**options},
              event_availability='recorded' if all('available_at_s' in e and e['available_at_s']!='' for e in events) else 'legacy_end_s_approximation',
              definitions=dict(interval='both endpoints valid and available by window end; gaps/tail are unknown; no extrapolation',
                               eye_ratio='threshold-based bilateral closed time / valid eye time; not standardized PERCLOS',
                               events='candidate count by available_at_s in [start,end); flags excluded',
                               longest='strict observed CLOSED interval inside window; lower bound',
                               overlap='mouth OPEN is a proxy, not a verified yawn label',
                               ear='continuous bilateral valid geometry; includes state UNKNOWN if ears valid; time-weighted left-endpoint values',
                               ear_normalization='EAR / preceding completed open-eye baseline per eye; no clipping; missing baseline stays null',
                               ear_p10='inverse time-weighted CDF at .10; not a diagnosis or threshold',
                               model_input_usable='all_channels_usable AND ear_norm_usable'),
              training='labels intentionally blank; split by subject/video before windowing; do not randomly split overlapping windows')
    output_path.with_suffix('.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return output_path,features
