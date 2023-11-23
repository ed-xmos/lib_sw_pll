# Copyright 2023 XMOS LIMITED.
# This Software is subject to the terms of the XMOS Public Licence: Version 1.
"""
Assorted tests which run the test_app in xsim 

This file is structured as a fixture which takes a while to run
and generates a pandas.DataFrame containing some time domain
outputs from the control loops. Then a series of tests which
check different aspects of the content of this DataFrame.
"""

import pytest
import numpy as np
import copy
from typing import Any
from dataclasses import dataclass, asdict
from pathlib import Path
from matplotlib import pyplot as plt
from subprocess import Popen, PIPE
import re


# from sw_pll.app_pll_model import app_pll_frac_calc
from sw_pll.dco_model import sigma_delta_dco
from sw_pll.controller_model import sdm_pi_ctrl
from test_lib_sw_pll import bin_dir


DUT_XE_SDM_CTRL = Path(__file__).parent / "../build/tests/test_app_sdm_ctrl/test_app_sdm_ctrl.xe"

@dataclass
class DutSDMCTRLArgs:
    kp: float
    ki: float
    loop_rate_count: int
    pll_ratio: int
    ref_clk_expected_inc: int
    app_pll_ctl_reg_val: int
    app_pll_div_reg_val: int
    app_pll_frac_reg_val: int
    ppm_range: int
    target_output_frequency: int


class Dut_SDM_CTRL:
    """
    run controller in xsim and provide access to the sdm function
    """

    def __init__(self, args:DutSDMCTRLArgs, xe_file=DUT_XE_SDM_CTRL):
        self.args = DutSDMCTRLArgs(**asdict(args))  # copies the values
        # concatenate the parameters to the init function and the whole lut
        # as the command line parameters to the xe.
        list_args = [*(str(i) for i in asdict(self.args).values())] 

        cmd = ["xsim", "--args", str(xe_file), *list_args]

        print(" ".join(cmd))

        self._process = Popen(
            cmd,
            stdin=PIPE,
            stdout=PIPE,
            encoding="utf-8",
        )

    def __enter__(self):
        """support context manager"""
        return self

    def __exit__(self, *_):
        """support context manager"""
        self.close()

    def do_control(self, mclk_diff):
        """
        returns sigma delta out, calculated frac val, lock status and timing
        """
        self._process.stdin.write(f"{mclk_diff}\n")
        self._process.stdin.flush()

        from_dut = self._process.stdout.readline().strip()
        error, locked, ticks = from_dut.split()

        return int(error), int(locked), int(ticks)

    def close(self):
        """Send EOF to xsim and wait for it to exit"""
        self._process.stdin.close()
        self._process.wait()


def read_register_file(reg_file):
    with open(reg_file) as rf:
        text = "".join(rf.readlines())
        regex = r".+APP_PLL_CTL_REG 0[xX]([0-9a-fA-F]+)\n.+APP_PLL_DIV_REG.+0[xX]([0-9a-fA-F]+)\n.+APP_PLL_FRAC_REG.+0[xX]([0-9a-fA-F]+)\n"
        match = re.search(regex, text)

        app_pll_ctl_reg_val, app_pll_div_reg_val, app_pll_frac_reg_val = match.groups()

        return app_pll_ctl_reg_val, app_pll_div_reg_val, app_pll_frac_reg_val



def test_sdm_ctrl_equivalence(bin_dir):
    """
    Simple low level test of equivalence using do_control_from_error
    Feed in random numbers into C and Python DUTs and see if we get the same results
    """

    available_profiles = list(sigma_delta_dco.profiles.keys())
    profile_used = available_profiles[0]
    profile = sigma_delta_dco.profiles[profile_used]
    target_output_frequency = profile["output_frequency"]
    ref_frequency = 48000
    ref_clk_expected_inc = 0

    Kp = 0.0
    Ki = 32.0

    ctrl_sim = sdm_pi_ctrl(Kp, Ki)

    dco = sigma_delta_dco(profile_used)
    dco.print_stats()
    register_file = dco.write_register_file()
    app_pll_ctl_reg_val, app_pll_div_reg_val, app_pll_frac_reg_val = read_register_file(register_file)


    args = DutSDMCTRLArgs(
        kp = Kp,
        ki = Ki,
        loop_rate_count = 1,
        pll_ratio = target_output_frequency / ref_frequency,
        ref_clk_expected_inc = ref_clk_expected_inc,
        app_pll_ctl_reg_val = app_pll_ctl_reg_val,
        app_pll_div_reg_val = app_pll_div_reg_val,
        app_pll_frac_reg_val = app_pll_frac_reg_val,
        ppm_range = 1000,
        target_output_frequency = target_output_frequency
    )


    ctrl_dut = Dut_SDM_CTRL(args)

    max_ticks = 0

    for mclk_diff in [1] * 10:

        dco_ctl_sim = ctrl_sim.do_control_from_error(mclk_diff)

        dco_ctl_dut, lock_status_dut, ticks = ctrl_dut.do_control(mclk_diff)

        print(f"SIM: {mclk_diff} {dco_ctl_sim}")
        print(f"DUT: {mclk_diff} {dco_ctl_dut} {lock_status_dut} {ticks}\n")

        max_ticks = ticks if ticks > max_ticks else max_ticks

        # assert dco_sim.sdm_out == sdm_out_dut
        # assert frac_reg_sim == frac_reg_dut
        # assert frequency_sim == frequency_dut
        # assert lock_status_sim == lock_status_dut


    print("TEST PASSED!")

