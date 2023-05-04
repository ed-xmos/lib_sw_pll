#**********************
# Gather Sources
#**********************
file(GLOB_RECURSE APP_SOURCES ${CMAKE_CURRENT_LIST_DIR}/src/*.c ${CMAKE_CURRENT_LIST_DIR}/src/*.xc)
set(APP_INCLUDES
    ${CMAKE_CURRENT_LIST_DIR}/src;
    ${CMAKE_CURRENT_LIST_DIR}/../../modules/lib_xcore_math/lib_xcore_math/api
)

message(I2S_APP_INCLUDES="${APP_INCLUDES}")

#**********************
# Flags
#**********************
set(APP_COMPILER_FLAGS
    -Os
    -g
    -report
    -fxscope
    -mcmodel=large
    -Wno-xcore-fptrgroup
    ${CMAKE_CURRENT_LIST_DIR}/src/config.xscope
    ${CMAKE_CURRENT_LIST_DIR}/src/xvf3800_qf60.xn
)
set(APP_COMPILE_DEFINITIONS
)

set(APP_LINK_OPTIONS
    -report
    ${CMAKE_CURRENT_LIST_DIR}/src/config.xscope
    ${CMAKE_CURRENT_LIST_DIR}/src/xvf3800_qf60.xn
)

#**********************
# Tile Targets
#**********************
add_executable(i2s_slave)
target_sources(i2s_slave PUBLIC ${APP_SOURCES})
target_include_directories(i2s_slave PUBLIC ${APP_INCLUDES})
target_compile_definitions(i2s_slave PRIVATE ${APP_COMPILE_DEFINITIONS})
target_compile_options(i2s_slave PRIVATE ${APP_COMPILER_FLAGS})
target_link_options(i2s_slave PRIVATE ${APP_LINK_OPTIONS})
target_link_libraries(i2s_slave PUBLIC io::sw_pll lib_i2s)
