# Copyright 2022-2023 XMOS LIMITED.
# This Software is subject to the terms of the XMOS Public Licence: Version 1.

import numpy as np
import matplotlib.pyplot as plt
import subprocess
import re
import os
import pll_vcd

header_file = "fractions.h"   # fixed name by pll_calc.py
register_file = "register_setup.h" # can be changed as needed

nominal_ref_frequency = 48000.0
target_mclk_frequency = 12288000
multiplier = target_mclk_frequency / nominal_ref_frequency
ref_to_loop_call_rate = 512          # call comntrol once every n ref clocks
xtal_frequency = 24000000


class app_pll_frac_calc:
    """ 
        This class uses the formula in the XU316 datasheet to calculate the output frequency of the
        application PLL (sometimes called secondary PLL) from the register settings provided.
        It uses the checks specified in the datasheet to ensure the settings are valid, and will assert if not.
        To keep the inherent jitter of the PLL output down to a minimum, it is recommended that R be kept small,
        ideally = 0 (which equiates to 1) but reduces lock range.
    """
    def __init__(self, input_frequency, F_init, R_init, OD_init, ACD_init, f_init, r_init, verbose=False):
        self.input_frequency = input_frequency
        self.F = F_init 
        self.R = R_init  
        self.OD = OD_init
        self.ACD = ACD_init
        self.f = f_init                 # fractional multiplier (+1.0)
        self.p = r_init                 # fractional fivider (+1.0)           
        self.output_frequency = None
        self.lock_status_state = 0
        self.verbose = verbose

        self.calc_frequency()

    def calc_frequency(self):
        if self.verbose:
            print(f"F: {self.F} R: {self.R} OD: {self.OD} ACD: {self.ACD} f: {self.f} p: {self.p}")
            print(f"input_frequency: {self.input_frequency}")
        assert self.F >= 1 and self.F <= 8191, f"Invalid F setting {self.F}"
        assert type(self.F) is int, f"Error: F must be an INT"
        assert self.R >= 0 and self.R <= 63, f"Invalid R setting {self.R}"
        assert type(self.R) is int, f"Error: R must be an INT"
        assert self.OD >= 0 and self.OD <= 7, f"Invalid OD setting {self.OD}"
        assert type(self.OD) is int, f"Error: OD must be an INT"

        intermediate_freq = self.input_frequency * (self.F + 1.0) / 2.0 / (self.R + 1.0)
        assert intermediate_freq >= 360000000.0 and intermediate_freq <= 1800000000.0, f"Invalid VCO freq: {intermediate_freq}"
        # print(f"intermediate_freq: {intermediate_freq}")

        assert type(self.p) is int, f"Error: r must be an INT"
        assert type(self.f) is int, f"Error: f must be an INT"

        assert self.p > self.f, "Error f is not < p: {self.f} {self.p}"

        # From XU316-1024-QF60A-xcore.ai-Datasheet_22.pdf
        self.output_frequency = self.input_frequency * (self.F + 1.0 + ((self.f + 1) / (self.p + 1)) ) / 2.0 / (self.R + 1.0) / (self.OD + 1.0) / (2.0 * (self.ACD + 1))

        return self.output_frequency

    def get_output_freqency(self):
        return self.output_frequency

    def update_pll_all(self, F, R, OD, ACD, f, p):
        self.F = F
        self.R = R 
        self.OD = OD
        self.ACD = ACD
        self.f = f
        self.p = p
        self.calc_frequency()

    def update_pll_frac(self, f, p):
        self.f = f
        self.p = p
        self.calc_frequency()

class parse_lut_h_file():
    """ 
        This class parses a pre-generated fractions.h file and builds a lookup table so that the values can be
        used by the sw_pll simulation. It may be used directly but is generally used a sub class of error_to_pll_output_frequency.
    """
    def __init__(self, header_file, verbose=False):        
        with open(header_file) as hdr:
            header = hdr.readlines()
            min_frac = 1.0
            max_frac = 0.0
            for line in header:
                regex_ne = fr"frac_values_?\d*\[(\d+)].*"
                match = re.search(regex_ne, line)
                if match:
                    num_entries = int(match.groups()[0])
                    # print(f"num_entries: {num_entries}")
                    lut = np.zeros(num_entries, dtype=np.uint16)

                regex_fr = r"0x([0-9A-F]+).+Index:\s+(\d+).+=\s(0.\d+)"
                match = re.search(regex_fr, line)
                if match:
                    reg, idx, frac = match.groups()
                    reg = int(reg, 16)
                    idx = int(idx)
                    frac = float(frac)
                    min_frac = frac if frac < min_frac else min_frac
                    max_frac = frac if frac > max_frac else max_frac
                    lut[idx] = reg

            # print(f"min_frac: {min_frac} max_frac: {max_frac}")

            self.lut_reg = lut
            self.min_frac = min_frac
            self.max_frac = max_frac

    def get_lut(self):
        return self.lut_reg

    def get_lut_size(self):
        return np.size(self.lut_reg)

class error_to_pll_output_frequency(app_pll_frac_calc, parse_lut_h_file):
    """ 
        This super class combines app_pll_frac_calc and parse_lut_h_file and provides a way of inputting the eror signal and
        providing an output frequency for a given set of PLL configuration parameters. It includes additonal methods for
        turning the LUT register settings parsed by parse_lut_h_file into fractional values which can be fed into app_pll_frac_calc.

        It also contains information reporting methods which provide the range and step sizes of the PLL configuration as well as 
        plotting the transfer function from error to frequncy so the linearity and regularity the transfer function can be observed.
    """

    def __init__(self, header_file, input_frequency, F_init, R_init, OD_init, ACD_init, f_init, p_init, verbose=False):
        self.app_pll_frac_calc = app_pll_frac_calc.__init__(self, input_frequency, F_init, R_init, OD_init, ACD_init, f_init, p_init, verbose=False)
        self.parse_lut_h_file = parse_lut_h_file.__init__(self, header_file, verbose=False)
        self.verbose = verbose

    def reg_to_frac(self, register):
        f = (register & 0xff00) >> 8
        p = register & 0xff

        return f, p

    def get_output_freqency_from_error(self, error):
        lut = self.get_lut()
        num_entries = np.size(lut)

        set_point = num_entries // 2 - int(error) #  Note negative term for neg feedback
        if set_point < 0:
            set_point = 0
            lock_status = -1
        elif set_point >= num_entries:
            set_point = num_entries - 1
            lock_status = 1
        else:
            set_point = set_point
            lock_status = 0

        register = int(lut[set_point])
        f, p = self.reg_to_frac(register)

        if self.verbose:
            print(f"set_point: {set_point}, f: {f}, p: {p}, reg: 0x{register:04x}")
        self.update_pll_frac(f, p)

        return self.get_output_freqency(), lock_status

    def get_stats(self):
        lut = self.get_lut()
        steps = np.size(lut)

        register = int(lut[0])
        f, p = self.reg_to_frac(register)
        self.update_pll_frac(f, p)
        min_freq = self.get_output_freqency()

        register = int(lut[steps // 2])
        f, p = self.reg_to_frac(register)
        self.update_pll_frac(f, p)
        mid_freq = self.get_output_freqency()

        register = int(lut[-1])
        f, p = self.reg_to_frac(register)
        self.update_pll_frac(f, p)
        max_freq = self.get_output_freqency()

        return min_freq, mid_freq, max_freq, steps

    def plot_freq_range(self):
        lut = self.get_lut()
        steps = np.size(lut)

        frequencies = []
        for step in range(steps):
            register = int(lut[step])
            f, p = self.reg_to_frac(register)
            self.update_pll_frac(f, p)
            frequencies.append(self.get_output_freqency())

        plt.clf()
        plt.plot(frequencies, color='green', marker='.', label='frequency')
        plt.title('PLL fractional range', fontsize=14)
        plt.xlabel(f'LUT index', fontsize=14)
        plt.ylabel('Frequency', fontsize=10)
        plt.legend(loc="upper right")
        plt.grid(True)
        # plt.show()
        plt.savefig("sw_pll_range.png")

def parse_register_file(register_file):
    """
        This helper function reads the pre-saved register setup comments from get_pll_solution and parses them into parameters that
        can be used for the simulation.
    """

    with open(register_file) as rf:
        reg_file = rf.read().replace('\n', '')
        F = int(re.search(".+F:\s+(\d+).+", reg_file).groups()[0])
        R = int(re.search(".+R:\s+(\d+).+", reg_file).groups()[0])
        f = int(re.search(".+f:\s+(\d+).+", reg_file).groups()[0])
        p = int(re.search(".+p:\s+(\d+).+", reg_file).groups()[0])
        OD = int(re.search(".+OD:\s+(\d+).+", reg_file).groups()[0])
        ACD = int(re.search(".+ACD:\s+(\d+).+", reg_file).groups()[0])

    return F, R, f, p, OD, ACD



                                                              # see generating_lut_guide.txt for guidance on these settings
def get_pll_solution(input_frequency, target_output_frequency, max_denom=80, min_F=200, ppm_max=2, fracmin=0.8, fracmax=1.0):
    """
        This is a wrapper function for pll_calc.py and allows it to be called programatically.
        It contains sensible defaults for the arguments and abstracts some of the complexity away from 
        the underlying script. Configuring the PLL is not an exact science and there are many tradeoffs involved.
        See generating_lut_guide.rst for some of the tradeoffs involved and some example paramater sets.

        Once run, this function saves two output files:
        - fractions.h which contains the fractional term lookup table, which is guarranteed monotonic (important for PID stability)
        - register_setup.h which contains the PLL settings in comments as well as register settings for init in the application 

        This function and the underlying call to pll_calc may take several seconds to complete since it searches a range
        of possible solutions numerically.
    """
    input_frequency_MHz = input_frequency / 1000000.0
    target_output_frequency_MHz = target_output_frequency / 1000000.0

    #                       input freq,           app pll,  max denom,  output freq,  min phase comp freq, max ppm error,  raw, fractional range, make header
    cmd = f"./pll_calc.py -i {input_frequency_MHz}  -a -m {max_denom} -t {target_output_frequency_MHz} -p 6.0 -e {int(ppm_max)} -r --fracmin {fracmin} --fracmax {fracmax} --header"
    print(f"Running: {cmd}")
    output = subprocess.check_output(cmd.split(), text=True)

    # Get each solution
    solutions = []
    Fs = []
    regex = r"Found solution.+\nAPP.+\nAPP.+\nAPP.+"
    matches = re.findall(regex, output)

    for solution in matches:
        F = int(float(re.search(".+FD\s+(\d+.\d+).+", solution).groups()[0]))
        solutions.append(solution)
        Fs.append(F)

    possible_Fs = sorted(set(Fs))
    print(f"Available F values: {possible_Fs}")

    # Find first solution with F greater than F
    idx = next(x for x, val in enumerate(Fs) if val > min_F)    
    solution = matches[idx]

    # Get actual PLL register bitfield settings and info 
    regex = r".+OUT (\d+\.\d+)MHz, VCO (\d+\.\d+)MHz, RD\s+(\d+), FD\s+(\d+.\d*)\s+\(m =\s+(\d+), n =\s+(\d+)\), OD\s+(\d+), FOD\s+(\d+), ERR (-*\d+.\d+)ppm.*"
    match = re.search(regex, solution)

    if match:
        vals = match.groups()

        output_frequency = (1000000.0 * float(vals[0]))
        vco_freq = 1000000.0 * float(vals[1])

        # Now convert to actual settings in register bitfields
        F = int(float(vals[3]) - 1)     # PLL integer multiplier
        R = int(vals[2]) - 1            # PLL integer divisor
        f = int(vals[4]) - 1            # PLL fractional multiplier
        p = int(vals[5]) - 1            # PLL fractional divisor
        OD = int(vals[6]) - 1           # PLL output divider
        ACD = int(vals[7]) - 1          # PLL application clock divider
        ppm = float(vals[8])            # PLL PPM error for requrested set frequency
    
    assert match, f"Could not parse output of: {cmd} output: {solution}"

    # Now get reg values and save to file
    with open(register_file, "w") as reg_vals:
        reg_vals.write(f"/* Autogenerated by {os.path.basename(__file__)} using command line:\n")
        reg_vals.write(f"   {cmd}\n")
        reg_vals.write(f"   Picked output solution #{idx}\n")
        # reg_vals.write(f"\n{solution}\n\n") # This is verbose and contains the same info as below
        reg_vals.write(f"   F: {F}\n")
        reg_vals.write(f"   R: {R}\n")
        reg_vals.write(f"   f: {f}\n")
        reg_vals.write(f"   p: {p}\n")
        reg_vals.write(f"   OD: {OD}\n")
        reg_vals.write(f"   ACD: {ACD}\n")
        reg_vals.write(f"   Output freq: {output_frequency}\n")
        reg_vals.write(f"   VCO freq: {vco_freq} */\n")
        reg_vals.write("\n")


        for reg in ["APP PLL CTL REG", "APP PLL DIV REG", "APP PLL FRAC REG"]:
            regex = rf"({reg})\s+(0[xX][A-Fa-f0-9]+)"
            match = re.search(regex, solution)
            if match:
                val = match.groups()[1]
                reg_name = reg.replace(" ", "_")
                line = f"#define {reg_name}  \t{val}\n"
                reg_vals.write(line)


    return output_frequency, vco_freq, F, R, f, p, OD, ACD, ppm 


class sw_pll_ctrl:
    """
        This class instantiates a control loop instance. It takes a lookup table function which can be generated 
        from the error_from_h class which allows it use the actual pre-calculated transfer function.
        Once instantiated, the do_control method runs the control loop.

        This class forms the core of the simulator and allows the constants (K..) to be tuned to acheive the 
        desired response. The function run_sim allows for a plot of a step resopnse input which allows this
        to be done visually.
    """
    lock_status_lookup = {-1 : "UNLOCKED LOW", 0 : "LOCKED", 1 : "UNLOCKED HIGH"}

    def __init__(self, lut_lookup_function, lut_size, multiplier, ref_to_loop_call_rate, Kp, Ki, Kii=0.0, init_mclk_count=0, init_ref_clk_count=0, verbose=False):
        self.lut_lookup_function = lut_lookup_function
        self.multiplier = multiplier
        self.ref_to_loop_call_rate = ref_to_loop_call_rate

        self.ref_clk_count = init_mclk_count    # Integer as we run this loop based on the ref clock input count
        self.mclk_count_old = init_mclk_count   # Integer
        self.expected_mclk_count_inc_float = multiplier * ref_to_loop_call_rate
        self.expected_mclk_count_float = 0.0

        self.Kp     = Kp
        self.Ki     = Ki
        self.Kii    = Kii

        self.error_accum = 0.0          #Integral of error
        self.error_accum_accum = 0.0    #Double integral
        self.error = 0.0                #total error

        self.i_windup_limit     = lut_size / Ki if Ki != 0.0 else 0.0
        self.ii_windup_limit    = lut_size / Kii if Kii != 0.0 else 0.0

        self.last_mclk_frequency = target_mclk_frequency

        self.verbose = verbose

        if verbose:
            print(f"Init sw_pll_ctrl, target_mclk_frequency: {target_mclk_frequency} ref_to_loop_call_rate: {ref_to_loop_call_rate}, Kp: {Kp} Ki: {Ki}")

    def get_expected_mclk_count_inc(self):
        return self.expected_mclk_count_inc_float

    def get_error(self):
        return self.error

    def do_control(self, mclk_count_float, period_fraction=1.0):

        """ Calculate the actual output frequency from the input mclk_count taken at the ref clock time.
            If the time of sampling the mclk_count is not precisely 1.0 x the ref clock time,
            you may pass a fraction to allow for a proportional value using period_fraction. This is optional.
        """

        mclk_count_int = int(mclk_count_float)
        mclk_count_inc = mclk_count_int - self.mclk_count_old
        mclk_count_inc = mclk_count_inc / period_fraction

        self.mclk_count_old = mclk_count_int
        self.expected_mclk_count_float += self.expected_mclk_count_inc_float

        self.ref_clk_count += self.ref_to_loop_call_rate

        error = mclk_count_inc - int(self.expected_mclk_count_inc_float)

        self.error_accum += error 
        self.error_accum_accum += self.error_accum

        error_p  = self.Kp * error;
        error_i  = self.Ki * self.error_accum
        error_ii = self.Kii * self.error_accum_accum

        # Clamp integral terms
        error_i = np.clip(error_i, -self.i_windup_limit, self.i_windup_limit)
        error_ii = np.clip(error_ii, -self.ii_windup_limit, self.ii_windup_limit)

        self.error = error_p + error_i + error_ii

        if self.verbose:
            print(f"diff: {error} error_p: {error_p}({self.Kp}) error_i: {error_i}({self.Ki}) error_ii: {error_ii}({self.Kii}) total error: {self.error}")


        if self.verbose:
            print(f"expected mclk_count: {self.expected_mclk_count} actual mclk_count: {self.mclk_count} error: {self.error}")

        actual_mclk_frequency, lock_status = self.lut_lookup_function(self.error)

        return actual_mclk_frequency, lock_status





def run_sim(nominal_ref_frequency, lut_lookup_function, lut_size, verbose=False):
    """
        This function uses the sw_pll_ctrl and passed lut_lookup_function to run a simulation of the response
        of the sw_pll to changes in input reference frequency.
        A plot of the simulation is generated to allow visual inspection and tuning.
    """
    ref_frequency = nominal_ref_frequency
    sw_pll = sw_pll_ctrl(lut_lookup_function, lut_size, multiplier, ref_to_loop_call_rate, 0.1, 2.0, Kii=0.0, verbose=False)
    mclk_count_end_float = 0.0
    real_time = 0.0
    # actual_mclk_frequency = target_mclk_frequency
    actual_mclk_frequency = target_mclk_frequency * (1 - 200 / 1000000)# initial value which is some PPM off

    freq_log = []
    target_log = []

    vcd = pll_vcd.sw_pll_vdd()

    for count in range(150):
        mclk_count_start_float = mclk_count_end_float
        mclk_count_float_inc = actual_mclk_frequency / ref_frequency * ref_to_loop_call_rate
     
        # Add some jitter to the mclk_count
        mclk_sample_jitter = 0
        mclk_sample_jitter = 100 * (np.random.sample() - 0.5)         
        mclk_count_end_float += mclk_count_float_inc + mclk_sample_jitter
        # Compensate for the jitter
        period_fraction = (mclk_count_float_inc + mclk_sample_jitter) / mclk_count_float_inc

        # print(f"mclk_count_float_inc: {mclk_count_float_inc}, period_fraction: {period_fraction}, ratio: {mclk_count_float_inc / period_fraction}")

        actual_mclk_frequency, lock_status = sw_pll.do_control(mclk_count_end_float, period_fraction = period_fraction)
        
        # vcd.do_vcd(real_time, ref_frequency, mclk_count_start_float, mclk_count_end_float, sw_pll.get_error(), count, lock_status)

        if verbose:
            print(f"Loop: count: {count}, actual_mclk_frequency: {actual_mclk_frequency}, lock_status: {sw_pll_ctrl.lock_status_lookup[lock_status]}")
     
        freq_log.append(actual_mclk_frequency)
        target_log.append(ref_frequency * multiplier)

        real_time += ref_to_loop_call_rate / ref_frequency

        ppm_adjust = lambda f, ppm: f * (1 + (ppm / 1000000))

        if count == 25:
            ref_frequency = ppm_adjust(nominal_ref_frequency, 300)

        if count == 50:
            ref_frequency = ppm_adjust(nominal_ref_frequency, 150)

        if count == 80:
            ref_frequency = ppm_adjust(nominal_ref_frequency, -300)

        if count == 130:
            ref_frequency = ppm_adjust(nominal_ref_frequency, 0)


    plt.clf()
    plt.plot(freq_log, color='red', marker='o', label='actual frequency')
    plt.plot(target_log, color='blue', marker='.', label='target frequency')
    plt.title('PLL tracking', fontsize=14)
    plt.xlabel(f'loop_cycle {ref_to_loop_call_rate}', fontsize=14)
    plt.ylabel('Frequency', fontsize=10)
    plt.legend(loc="upper right")
    plt.grid(True)
    # plt.show()
    plt.savefig("pll_step_response.png")

if __name__ == '__main__':
    """
        This script checks to see if PLL settings have already been generated, if not, generates them.
        It then uses these settings to generate a LUT and control loop instance. 
        A set of step functions in input reference frequencies are then generated and the
        response of the sw_pll to these changes is logged and then plotted.
    """

    # Use pre-caclulated saved values if they exist, otherwise generate new ones
    if not os.path.exists(header_file) or not os.path.exists(register_file):
        output_frequency, vco_freq, F, R, f, p, OD, ACD, ppm = get_pll_solution(xtal_frequency, target_mclk_frequency)
        print(f"output_frequency: {output_frequency}, vco_freq: {vco_freq}, F: {F}, R: {R}, f: {f}, p: {p}, OD: {OD}, ACD: {ACD}, ppm: {ppm}")
    else:
        F, R, f, p, OD, ACD = parse_register_file(register_file)
        print(f"Using pre-calculated settings read from {header_file} and {register_file}:\n")

    print(f"PLL register settings F: {F}, R: {R}, OD: {OD}, ACD: {ACD}, f: {f}, p: {p}")

    # Instantiate controller
    error_from_h = error_to_pll_output_frequency(header_file, xtal_frequency, F, R, OD, ACD, f, p, verbose=False)
    error_from_h.plot_freq_range()
    
    min_freq, mid_freq, max_freq, steps = error_from_h.get_stats()
    print(f"min_freq: {min_freq}Hz\n" f"mid_freq: {mid_freq}Hz\n" f"max_freq: {max_freq}Hz\n" f"average step size: {((max_freq - min_freq) / steps):.6}Hz\n" f"LUT entries: {steps}\n" f"PPM range: +-{1e6 * (max_freq / min_freq - 1) / 2}")

    run_sim(nominal_ref_frequency, error_from_h.get_output_freqency_from_error, error_from_h.get_lut_size())