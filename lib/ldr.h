#ifndef LDR_H
#define LDR_H

#include "esp_err.h"
/* DRV8833 must be initialized before starting automatic day/night control. */
esp_err_t ldr_start(void);

#endif
