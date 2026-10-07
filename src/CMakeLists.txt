idf_component_register(
    SRCS
        "main.c"
        "../lib/camera.c"
        "../lib/drv8833.c"
        "../lib/ldr.c"
        "../lib/usb_camera.c"
    INCLUDE_DIRS "../lib"
    PRIV_REQUIRES
        esp32-camera
        esp_driver_gpio
        esp_driver_ledc
        esp_adc
        usb_device_uvc
        espressif__tinyusb
        esp_timer
)

# usb_device_uvc publishes usb_descriptors.c as a PUBLIC TinyUSB source.
# PlatformIO would compile the same file for two libraries with different flags.
# Keep it in TinyUSB's own sources, without propagating it to dependent targets.
idf_component_get_property(tinyusb_lib espressif__tinyusb COMPONENT_LIB)
target_include_directories(${tinyusb_lib} PUBLIC "${CMAKE_CURRENT_LIST_DIR}/../lib")
target_compile_definitions(${tinyusb_lib} PUBLIC CFG_TUSB_CONFIG_FILE="usb_camera_tusb_config.h")
get_target_property(tinyusb_interface_sources ${tinyusb_lib} INTERFACE_SOURCES)
if(tinyusb_interface_sources)
    list(FILTER tinyusb_interface_sources EXCLUDE REGEX "/usb_descriptors\\.c$")
    set_property(TARGET ${tinyusb_lib} PROPERTY INTERFACE_SOURCES "${tinyusb_interface_sources}")
endif()
