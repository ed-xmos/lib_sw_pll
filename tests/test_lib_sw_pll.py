"""
Assorted tests which run the test_app in xsim 
"""

from typing import Any
from sw_pll.sw_pll_sim import pll_solution, app_pll_frac_calc
from dataclasses import dataclass, asdict
from subprocess import Popen, PIPE
from pathlib import Path

DUT_XE = Path(__file__).parent / "../build/tests/test_app/test_app.xe"

@dataclass
class DutArgs:
    kp: int
    ki: int
    kii: int
    loop_rate_count: int
    pll_ratio: int
    ref_clk_expected_inc: int
    lut: Any 
    app_pll_ctl_reg_val: int
    app_pll_div_reg_val: int
    nominal_lut_idx: int
    ppm_range: int


class Dut:
    """
    run pll in xsim and provide access to the control function
    """
    def __init__(
        self,
        args: DutArgs
    ):
        lut = args.lut
        args.lut = len(args.lut)
        args = [*(str(i) for i in asdict(args).values())] + [str(i) for i in lut]

        cmd = ["xsim", "--args", str(DUT_XE), *args]

        print(len(" ".join(cmd)))
        print(" ".join(cmd))

        self.lut = lut
        self.args = args
        self._process = Popen(
            cmd,
            stdin=PIPE,
            stdout=PIPE,
            encoding="utf-8",
        )

    def do_control(self, mclk_pt, ref_pt):
        """
        returns lock_state, reg_val
        """
        self._process.stdin.write(f"{mclk_pt} {ref_pt}\n")
        self._process.stdin.flush()

        locked, reg = self._process.stdout.readline().strip().split()
        return int(locked), int(reg, 16)

    def close(self):
        self._process.stdin.close()
        self._process.wait()

def q_number(f, frac_bits):
    return int(f * (2**frac_bits))

q16 = lambda n: q_number(n, 16)

# def test_iter(dut, sol, pll):
#     locked, reg = dut.do_control(0, 0)
#     yield locked, reg


def test_example():
    """
    test the sunny day case where the reference is running at the desired frequency,
    start low and check that the lock is acquired.
    """
    xtal_freq = 24e6
    target_mclk_f = 12.288e6
    bclk_per_lrclk = 64
    target_ref_f = 48e3 * bclk_per_lrclk  # 64 bclk per sample
    
    ref_pt_per_loop = bclk_per_lrclk * 512  # call the function every 512 samples rather than 
                                            # every sample to speed things up.
    loop_rate_count = 1
    loop_time = ref_pt_per_loop * (1/target_ref_f)

    # Generate init parameters
    sol = pll_solution(xtal_freq, target_mclk_f)
    start_reg = sol.lut.get_lut()[0]
    args = DutArgs(
            kp=q16(0),
            ki=q16(1),
            kii=q16(0),
            loop_rate_count=loop_rate_count, # copied from ed's setup in 3800
                                    # have to call 512 times to do 1 
                                    # control update
            pll_ratio=int(target_mclk_f/(target_ref_f/ref_pt_per_loop)),
            ref_clk_expected_inc=ref_pt_per_loop,
            app_pll_ctl_reg_val=0,   # TODO maybe we should check this somehow
            app_pll_div_reg_val=start_reg,
            nominal_lut_idx=0,       # start low so there is some controll to do
            ppm_range=int(sol.ppm),
            lut=sol.lut.get_lut(),
    )


    dut = Dut(args)
    pll = app_pll_frac_calc(
        xtal_freq, sol.F, sol.R, sol.OD, sol.ACD, 1, 2
    )
    pll.update_pll_frac_reg(start_reg)
    print(pll.get_output_freqency())
    assert (-1, int(sol.lut.get_lut()[0])) == dut.do_control(0, 0)

    ref_pt = 0
    mclk_pt = 0
    locked = -1
    results = {"target": [], "mclk": [], "reg": []}
    while locked != 0:
        print("elapsed r, m: ", ref_pt_per_loop, loop_time*pll.get_output_freqency())

        ref_pt = (ref_pt + ref_pt_per_loop)
        mclk_pt = (mclk_pt + (loop_time * pll.get_output_freqency()))
        locked, reg = dut.do_control(int(mclk_pt % 2**16), int(ref_pt % 2**16))
        
        pll.update_pll_frac_reg(reg)

        print(locked, pll.get_output_freqency(), target_mclk_f)
        results["target"].append(target_mclk_f)
        results["mclk"].append(pll.get_output_freqency())
        results["reg"].append(reg)


        











