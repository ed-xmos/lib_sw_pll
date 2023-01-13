// Copyright 2022-2023 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <xscope.h>
#include <xs1.h>

#include "sw_pll.h"
#include "i2s.h"

#define MCLK_FREQUENCY              12288000
#define I2S_FREQUENCY               48000
#define PLL_RATIO                   (MCLK_FREQUENCY / REF_FREQUENCY)
#define CONTROL_LOOP_COUNT          512
#define PPM_RANGE                   150

#define APP_PLL_CTL_12288           0x0881FA03
#define APP_PLL_DIV_12288           0x8000001E
#define APP_PLL_NOMINAL_INDEX_12288 35

#define NUM_I2S_CHANNELS            2
#define NUM_I2S_LINES               ((NUM_I2S_CHANNELS + 1) / 2)

//Found solution: IN 24.000MHz, OUT 12.288018MHz, VCO 3047.43MHz, RD  4, FD  507.905 (m =  19, n =  21), OD  2, FOD   31, ERR +1.50ppm
#include "fractions.h"

void setup_recovered_ref_clock_output(port_t p_recovered_ref_clk, xclock_t clk_recovered_ref_clk, port_t p_mclk, unsigned divider)
{
    // Connect clock block with divide to mclk
    clock_enable(clk_recovered_ref_clk);
    clock_set_source_port(clk_recovered_ref_clk, p_mclk);
    clock_set_divide(clk_recovered_ref_clk, divider / 2);
    printf("Divider: %u\n", divider);

    // Output the divided mclk on a port
    port_enable(p_recovered_ref_clk);
    port_set_clock(p_recovered_ref_clk, clk_recovered_ref_clk);
    port_set_out_clock(p_recovered_ref_clk);
    clock_start(clk_recovered_ref_clk);
}

typedef struct i2s_callback_args_t {
    bool did_restart;                       // Set by init
    int lock_status;
    int32_t loopback_samples[NUM_I2S_CHANNELS];
    port_t p_mclk_count;                    // Used for keeping track of MCLK output for clock recovery builds
    sw_pll_state_t *sw_pll;                 // Pointer to sw_pll state (if used)

} i2s_callback_args_t;


I2S_CALLBACK_ATTR
static void i2s_init(void *app_data, i2s_config_t *i2s_config){
    printf("I2S init\n");
    i2s_callback_args_t *cb_args = app_data;
    i2s_config->mode = I2S_MODE_I2S;
    i2s_config->mclk_bclk_ratio = (MCLK_FREQUENCY / I2S_FREQUENCY);

    cb_args->did_restart = true;
}

I2S_CALLBACK_ATTR
static i2s_restart_t i2s_restart_check(void *app_data){
    printf("loop\n");
    return I2S_NO_RESTART;
}


I2S_CALLBACK_ATTR
static void i2s_send(void *app_data, size_t num_out, int32_t *i2s_sample_buf){
    i2s_callback_args_t *cb_args = app_data;

    for(int i = 0; i < NUM_I2S_CHANNELS; i++){
        i2s_sample_buf[i] = cb_args->loopback_samples[i];
    }
}

I2S_CALLBACK_ATTR
static void i2s_receive(void *app_data, size_t num_in, const int32_t *i2s_sample_buf){
    i2s_callback_args_t *cb_args = app_data;


    for(int i = 0; i < NUM_I2S_CHANNELS; i++){
        cb_args->loopback_samples[i] = i2s_sample_buf[i];
    }
}


void sw_pll_test(void){

    xclock_t clk_mclk = XS1_CLKBLK_1;
    port_t p_ref_clk = PORT_I2S_LRCLK;
    xclock_t clk_word_clk = XS1_CLKBLK_2;
    port_t p_ref_clk_count = XS1_PORT_32A;


    port_t p_i2s_dout[NUM_I2S_LINES] = {PORT_I2S_DATA1};
    port_t p_i2s_din[NUM_I2S_LINES] = {PORT_I2S_DATA0};
    port_t p_bclk = PORT_I2S_BCLK;
    port_t p_lrclk = PORT_I2S_LRCLK;
    port_t p_mclk = PORT_MCLK;
    port_t p_mclk_count = PORT_MCLK_COUNT;
    xclock_t ck_bclk = XS1_CLKBLK_3;

    port_enable(p_mclk);
    port_enable(p_bclk);
    // NOTE:  p_lrclk does not need to be enabled by the caller

    // setup_ref_and_mclk_ports_and_clocks(p_mclk, clk_mclk, p_ref_clk, clk_word_clk, p_ref_clk_count);

    // // Make a test output to observe the recovered mclk divided down to the refclk frequency
    // xclock_t clk_recovered_ref_clk = XS1_CLKBLK_3;
    // port_t p_recovered_ref_clk = PORT_I2S_DAC_DATA;
    // setup_recovered_ref_clock_output(p_recovered_ref_clk, clk_recovered_ref_clk, p_mclk, PLL_RATIO);
    
    // sw_pll_state_t sw_pll;
    // sw_pll_init(&sw_pll,
    //             SW_PLL_15Q16(0.0),
    //             SW_PLL_15Q16(1.0),
    //             SW_PLL_15Q16(0.01),
    //             CONTROL_LOOP_COUNT,
    //             PLL_RATIO,
    //             frac_values_80,
    //             SW_PLL_NUM_LUT_ENTRIES(frac_values_80),
    //             APP_PLL_CTL_12288,
    //             APP_PLL_DIV_12288,
    //             APP_PLL_NOMINAL_INDEX_12288,
    //             PPM_RANGE);


    // Initialise app_data
    i2s_callback_args_t app_data = {
        .did_restart = false,
        .lock_status = SW_PLL_LOCKED,
        .loopback_samples = {0},
        .p_mclk_count = p_mclk_count,
        // .sw_pll = &sw_pll
    };

    // Initialise callback function pointers
    i2s_callback_group_t i2s_cb_group;
    i2s_cb_group.init = i2s_init;
    i2s_cb_group.restart_check = i2s_restart_check;
    i2s_cb_group.receive = i2s_receive;
    i2s_cb_group.send = i2s_send;
    i2s_cb_group.app_data = &app_data;

    printf("Starting i2s_slave\n");

    i2s_slave(
            &i2s_cb_group,
            p_i2s_dout,
            NUM_I2S_LINES,
            p_i2s_din,
            NUM_I2S_LINES,
            p_bclk,
            p_lrclk,
            ck_bclk);


        // port_in(p_ref_clk_count);   // This blocks each time round the loop until it can sample input (rising edges of word clock). So we know the count will be +1 each time.
        // uint16_t mclk_pt =  port_get_trigger_time(p_ref_clk);// Get the port timer val from p_ref_clk (which is running from MCLK). So this is basically a 16 bit free running counter running from MCLK.
        // sw_pll_do_control(&sw_pll, mclk_pt);


        // if(sw_pll.lock_status != lock_status){
        //     lock_status = sw_pll.lock_status;
        //     const char msg[3][16] = {"UNLOCKED LOW\0", "LOCKED\0", "UNLOCKED HIGH\0"};
        //     printf("%s\n", msg[lock_status+1]);
        // }
}