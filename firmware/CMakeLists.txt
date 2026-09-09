cmake_minimum_required(VERSION 3.13)

set(PICO_BOARD pico2_w)
set(PICO_PLATFORM rp2350)

include($ENV{PICO_SDK_PATH}/pico_sdk_init.cmake)
project(claude_observer C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()

set(SRC ${CMAKE_CURRENT_LIST_DIR}/src)
set(GEN_C ${SRC}/display/assets_gen.c)
set(GEN_H ${SRC}/display/assets_gen.h)

# Zasoby generowane z images/*.png. Regeneracja automatyczna po zmianie zrodel.
file(GLOB ASSET_PNG ${CMAKE_CURRENT_LIST_DIR}/../images/*.png)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
add_custom_command(
    OUTPUT ${GEN_C} ${GEN_H}
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_LIST_DIR}/../tools/img2c.py --verify
    DEPENDS ${CMAKE_CURRENT_LIST_DIR}/../tools/img2c.py ${ASSET_PNG}
    COMMENT "img2c: generowanie zasobow z images/"
    VERBATIM
)
add_custom_target(assets DEPENDS ${GEN_C} ${GEN_H})

add_executable(claude_observer
    ${SRC}/main.c
    ${SRC}/display/framebuf.c
    ${SRC}/ui/widgets.c
    ${GEN_C}
)
add_dependencies(claude_observer assets)

target_include_directories(claude_observer PRIVATE
    ${SRC} ${SRC}/display ${SRC}/ui ${SRC}/link
)

target_link_libraries(claude_observer
    pico_stdlib
    pico_cyw43_arch_none
    pico_btstack_ble pico_btstack_cyw43
    hardware_spi hardware_dma hardware_adc hardware_pwm hardware_watchdog
)

pico_enable_stdio_usb(claude_observer 1)
pico_enable_stdio_uart(claude_observer 0)
pico_add_extra_outputs(claude_observer)
