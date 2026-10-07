#ifndef DRV8833_H
#define DRV8833_H

#include <stdbool.h>

#include "esp_err.h"
#include "driver/gpio.h"

/*
NOTE Cực kỳ quan trọng xóa là quên
 * ESP32-S3 -> DRV8833
 *
 * GPIO42 -> IN1 -> IR-CUT
 * GPIO41 -> IN2 -> IR-CUT
 *
 * GPIO40 -> IN3 -> IR LED
 * GPIO39 -> IN4 -> IR LED
 */

#define DRV_IN1    GPIO_NUM_42
#define DRV_IN2    GPIO_NUM_41

#define DRV_IN3    GPIO_NUM_40
#define DRV_IN4    GPIO_NUM_39

/*
 * IR-CUT chỉ cần pulse.
 */
#define IR_CUT_PULSE_MS 200

esp_err_t drv8833_init(void);

void drv8833_set_day(void);
void drv8833_set_night(void);

void drv8833_ir_on(void);
void drv8833_ir_off(void);

bool drv8833_is_night(void);
bool drv8833_is_ir_on(void);

#endif