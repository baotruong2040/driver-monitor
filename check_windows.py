"""Bước 5: chuyển báo cáo behavior thành cửa sổ đặc trưng."""
import argparse
from window_features import export


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frames',required=True)
    p.add_argument('--events',required=True)
    p.add_argument('--output')
    p.add_argument('--report',help='JSON lần chạy chứa baseline EAR; cần khi CSV cũ chưa có baseline')
    p.add_argument('--window',type=float,default=30)
    p.add_argument('--stride',type=float,default=5)
    p.add_argument('--max-gap',type=float,default=.2)
    p.add_argument('--min-valid',type=float,default=.8)
    a=p.parse_args()
    try:
        path,features=export(a.frames,a.events,a.output,report_path=a.report,window=a.window,stride=a.stride,max_gap=a.max_gap,min_valid=a.min_valid)
        print(f'Windows: {path}\nMetadata: {path.with_suffix(".json")}\nRows: {len(features)}; usable: {sum(r["all_channels_usable"] for r in features)}')
        print(f'EAR normalized windows: {sum(r["ear_norm_valid_s"]>0 for r in features)}; model input usable: {sum(r["model_input_usable"] for r in features)}')
    except (ValueError,OSError,TypeError,KeyError) as exc:
        p.exit(1,f'Error: {exc}\n')

if __name__=='__main__':main()
