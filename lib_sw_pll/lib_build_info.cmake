set(LIB_NAME lib_sw_pll)
set(LIB_VERSION 2.0.0)
set(LIB_INCLUDES api src)
set(LIB_COMPILER_FLAGS -Os -g)
set(LIB_DEPENDENT_MODULES "")

XMOS_REGISTER_MODULE()
