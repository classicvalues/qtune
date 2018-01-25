import pandas as pd
import numpy as np
import h5py
from scipy import optimize
from qtune.chrg_diag import find_lead_transition
import matplotlib.pyplot as plt
import qtune.Evaluator

known_evaluators = pd.Series([["parameter_tunnel_coupling"], ["parameter_time_rise", "parameter_time_fall"]],
                             ["evaluator_SMInterDotTCByLineScan", "evaluator_SMLeadTunnelTimeByLeadScan"])
known_evaluators = known_evaluators.sort_index()


class Analyzer:
    def __init__(self, filename: str=None):
        self.gate_names = None
        self.tunable_gate_names = None
        self._parameter_names = None
        self.evaluator_names = None
        if filename is not None:
            self.load_file(filename)
        else:
            self.root_group = None

    @property
    def parameter_names(self):
        if self._parameter_names is None:
            print("You need to load the Parameter names!")
        return self._parameter_names

    @parameter_names.setter
    def parameter_names(self, parameter_names):
        self._parameter_names = parameter_names

    def load_file(self, filename: str):
        self.root_group = h5py.File(filename, "r")
        gate_names = self.root_group["gate_names"][:]
        self.gate_names = gate_names
        self.tunable_gate_names = self.root_group["tunable_gate_names"][:]

    def load_parameter_names(self, tune_run_number=1):
        if self.root_group.__contains__("tunerun_" + str(tune_run_number) + "/tune_sequence"):
            parameter_containing_group = self.root_group["tunerun_" + str(tune_run_number) + "/tune_sequence"]
        elif self.root_group.__contains__("tunerun_" + str(tune_run_number) + "/gradient_setup_1"):
            parameter_containing_group = self.root_group["tunerun_" + str(tune_run_number) + "/gradient_setup_1"]
        else:
            print("parameter_names could not be loaded!")
            return
        self.parameter_names = parameter_containing_group["parameter_names"][:]

    def load_cd_gradient(self, gradient_number=1, tune_run_number=0):
        tune_run_group = self.load_tune_run_group(tune_run_number)
        if not tune_run_group.__contains__("charge_diagram_" + str(gradient_number)):
            if tune_run_number > 0:
                print("There is no gradient saved for the charge diagram number " + str(
                    gradient_number) + " in tune run number" + str(
                    tune_run_number) + ". We try to find it in a previous run, since it might have been copied.")
                self.load_cd_gradient(gradient_number, tune_run_number-1)
            else:
                print("There is no gradient saved for the charge diagram number " + str(
                    gradient_number) + " in tune run number" + str(
                    tune_run_number) + ".")

        cd_group = tune_run_group["charge_diagram_" + str(gradient_number)]
        gradient, covariance, noise = load_gradient_from_group(cd_group)
        return gradient, covariance, noise

    def load_cd_gradient_as_pd(self, gradient_number=1, tune_run_number=0):
        gradient, covariance, noise = self.load_cd_gradient(gradient_number, tune_run_number)
        gradient = pd.DataFrame(gradient, ["PosA", "PosB"], ["BA", "BB"])
        return gradient

    def load_gradient_setup(self, gradient_number=1, tune_run_number=0):
        cd_group = self.load_gradient_group(gradient_number=gradient_number, tune_run_number=tune_run_number)
        gradient, covariance, noise = load_gradient_from_group(cd_group)
        return gradient, covariance, noise

    def load_gradient_tunerun(self, step_number: int=1, tune_run_number=1):
        tune_run_group = self.load_tune_run_group(tune_run_number)
        tune_sequence_group = tune_run_group["tune_sequence"]
        if tune_sequence_group.__contains__("step_" + str(step_number)):
            step_group = tune_sequence_group["step_" + str(step_number)]
        else:
            print("There is no group step " + str(step_number) + " in tune run number " + str(tune_run_number))
            return
        gradient, heuristic_covariance, heuristic_noise = load_gradient_from_group(step_group)
        return gradient, heuristic_covariance, heuristic_noise

    def load_gradient_pd(self, gradient_number=1, tune_run_number=0):
        if self.root_group.__contains__("tunerun_" + str(tune_run_number) + "/gradient_setup_" + str(gradient_number)):
            gradient, covariance, noise = self.load_gradient_setup(gradient_number=gradient_number, tune_run_number=tune_run_number)
        elif self.root_group.__contains__("tunerun_" + str(tune_run_number) + "/tune_sequence"):
            gradient, covariance, noise = self.load_gradient_tunerun(gradient_number, tune_run_number)
        else:
            gradient = None
            print("Gradient could not be loaded!")
        gradient = pd.DataFrame(gradient, self.parameter_names, self.tunable_gate_names)
        return gradient

    def load_gradient_sequence_pd(self, tune_run_number=1, start: int=0, end: int=None):
        self.load_parameter_names(tune_run_number=tune_run_number)
        tune_run_group = self.load_tune_run_group(tune_run_number)
        if end is None:
            end = count_steps_in_sequence(tune_run_group["tune_sequence"])
        gradient_sequence_pd = pd.DataFrame(None, index=self.parameter_names, columns=self.tunable_gate_names)
        for parameter in self.parameter_names:
            for gate in self.tunable_gate_names:
                gradient_sequence_pd[gate][parameter] = np.zeros((end + 1 - start, ))

        for counter in range(start, end):
            gradient_pd = self.load_gradient_pd(gradient_number=counter, tune_run_number=tune_run_number)
            for parameter in self.parameter_names:
                for gate in self.tunable_gate_names:
                    gradient_sequence_pd[gate][parameter][counter] = gradient_pd[gate][parameter]
        return gradient_sequence_pd

    def load_gate_voltages_and_parameters(self, data_group: h5py.Group) -> (pd.Series, pd.Series):
        if data_group.__contains__("gate_voltages"):
            gate_voltage_data_set = data_group["gate_voltages"]
            gate_voltages = gate_voltage_data_set[:]
            gate_voltages_pd = pd.Series(gate_voltages, self.gate_names)
        else:
            gate_voltages_pd = None

        parameter_name_list = []
        parameter_value_list = []
        for key in data_group.keys():
            if "evaluator_" in key:
                evaluator_data_set = data_group[key]
                for parameter_name in evaluator_data_set.attrs:
                    parameter_name_list += [str.encode(parameter_name)]
                    parameter_value_list += [evaluator_data_set.attrs[parameter_name]]
        parameters = pd.Series(parameter_value_list, parameter_name_list)
        parameters_pd = parameters.sort_index()
        return gate_voltages_pd, parameters_pd

    def load_gate_voltages_and_parameters_sequence(self, tune_run_number: int = 0, start: int = 0, end: int = None) -> (
            pd.Series, pd.Series):
        if start < 0:
            print("First step has number 0. There are no negative indices!")
            return
        tune_run_group = self.load_tune_run_group(tune_run_number)
        tune_sequence_group = tune_run_group["tune_sequence"]
        if end is None:
            end = count_steps_in_sequence(tune_sequence_group)
        gate_voltages_sequence_pd = pd.Series()
        for gate in self.gate_names:
            gate_voltages_sequence_pd[gate] = np.zeros((end - start, ))
        run_parameters = tune_sequence_group["parameter_names"][:]
        parameters_sequence_pd = pd.Series()
        for parameter in run_parameters:
            parameters_sequence_pd[parameter] = np.zeros((end - start, ))
        for counter in range(start, end):
            gate_voltages_pd, parameters_pd = self.load_gate_voltages_and_parameters(
                tune_sequence_group["step_" + str(counter)])
            for gate in self.gate_names:
                gate_voltages_sequence_pd[gate][counter] = gate_voltages_pd[gate]
            for parameter in self.parameter_names:
                parameters_sequence_pd[parameter][counter] = parameters_pd[parameter]
        return gate_voltages_sequence_pd, parameters_sequence_pd

    def load_desired_values(self, tune_run_number):
        tune_run_group = self.load_tune_run_group(tune_run_number)
        desired_values_pd = pd.Series(tune_run_group["desired_values"], self.parameter_names)
        return desired_values_pd

    def load_kalman_tune_run(self, tune_run_number=1, start: int=0, end: int=None):
        desired_values_pd = self.load_desired_values(tune_run_number)
        gate_voltages_sequence_pd, parameters_sequence_pd = self.load_gate_voltages_and_parameters_sequence(
            tune_run_number, start, end)
        gradient_sequence_pd = self.load_gradient_sequence_pd(tune_run_number=tune_run_number, start=start, end=end)
        return desired_values_pd, gate_voltages_sequence_pd, parameters_sequence_pd, gradient_sequence_pd

    def plot_kalman_tune_run(self, tune_run_number=1, start: int=0, end: int=None):
        desired_values_pd, gate_voltages_sequence_pd, parameters_sequence_pd, gradient_sequence_pd = \
            self.load_kalman_tune_run(tune_run_number, start, end)
        number_parameter = len(self.parameter_names)
        plt.figure(1)
        for i in range(number_parameter):
            plt.subplot(3, 1, i+1)
            plt.plot(parameters_sequence_pd[self.parameter_names[i]], "r")
            plt.axhline(desired_values_pd[self.parameter_names[i]])
            plt.ylabel(self.parameter_names[i].decode("ascii"))
        plt.figure(2)
        for gate in self.gate_names:
            plt.plot(gate_voltages_sequence_pd[gate])
        plt.legend([gate.decode("ascii") for gate in self.gate_names])
        plt.show()
        return

    def load_raw_measurement_pd(self, step_group):
        raw_measurement_pd = pd.Series()
        attribute_info_pd = pd.Series()
        for evaluator in self.evaluator_names:
            raw_measurement_pd[evaluator] = step_group[evaluator][:]
            attribute_info = {key: step_group[evaluator].attrs[key] for key in step_group[evaluator].attrs.keys()}
            attribute_info_pd[evaluator] = attribute_info
        return raw_measurement_pd, attribute_info_pd

    def load_raw_measurement_gradient_calculation(self, gradient_number: int = 1, tune_run_number: int = 0) -> (
            pd.DataFrame, pd.DataFrame, int, float):
        self.load_evaluator_names(tune_run_number=tune_run_number)
        gradient_group = self.load_gradient_group(gradient_number=gradient_number, tune_run_number=tune_run_number)
        delta_u = gradient_group.attrs["delta_u"]
#        delta_u = gradient_group["delta_u"].value
        n_repetitions = gradient_group.attrs["n_repetitions"]
#        n_repetitions = gradient_group["n_repetitions"].value
        raw_measurement_positive_detune_pd = pd.DataFrame(index=self.evaluator_names, columns=self.tunable_gate_names)
        raw_measurement_negative_detune_pd = pd.DataFrame(index=self.evaluator_names, columns=self.tunable_gate_names)
        parameter_positive_detune_pd = pd.DataFrame(index=self.evaluator_names, columns=self.tunable_gate_names)
        parameter_negative_detune_pd = pd.DataFrame(index=self.evaluator_names, columns=self.tunable_gate_names)
        for i in range(n_repetitions):
            for gate in self.tunable_gate_names:
                raw_measurement_pos_pd, attribute_info_pd_pos = self.load_raw_measurement_pd(
                    step_group=gradient_group["positive_detune_run_" + gate.decode("ascii") + "_" + str(i)])
                raw_measurement_neg_pd, attribute_info_pd_neg = self.load_raw_measurement_pd(
                    step_group=gradient_group["positive_detune_run_" + gate.decode("ascii") + "_" + str(i)])
                for evaluator in self.evaluator_names:
                    matrix_pos = raw_measurement_pos_pd[evaluator]
                    matrix_neg = raw_measurement_neg_pd[evaluator]
                    if i == 0:
                        raw_measurement_positive_detune_pd[gate][evaluator] = matrix_pos
                        raw_measurement_negative_detune_pd[gate][evaluator] = matrix_neg
                        parameter_positive_detune_pd[gate][evaluator] = attribute_info_pd_pos[evaluator]
                        parameter_negative_detune_pd[gate][evaluator] = attribute_info_pd_neg[evaluator]
                    else:
                        raw_measurement_positive_detune_pd[gate][evaluator] = np.concatenate(
                            (raw_measurement_positive_detune_pd[gate][evaluator], matrix_pos))
                        raw_measurement_negative_detune_pd[gate][evaluator] = np.concatenate(
                            (raw_measurement_negative_detune_pd[gate][evaluator], matrix_neg))
        return raw_measurement_positive_detune_pd, raw_measurement_negative_detune_pd, parameter_positive_detune_pd, \
            parameter_negative_detune_pd, n_repetitions, delta_u

    def plot_raw_measurement_gradient_calculation(self, gradient_number: int = 1, tune_run_number: int = 0):
        raw_measurement_positive_detune_pd, raw_measurement_negative_detune_pd, n_repetitions, delta_u = \
            self.load_raw_measurement_gradient_calculation(gradient_number=gradient_number,
                                                           tune_run_number=tune_run_number)
        print("Please chose a gate by typing the number next to its name: ")
        num_tunable_gates = len(self.tunable_gate_names)
        for i in range(num_tunable_gates):
            print(self.tunable_gate_names[i].decode("ascii") + ": " + str(i))
        gate = input()
        gate = int(gate)
        gate = self.tunable_gate_names[gate]
        print("please chose an evaluator by typing the number next to its name: ")
        num_evaluators = len(self.evaluator_names)
        for i in range(num_evaluators):
            print(self.evaluator_names[i] + ": " + str(i))
        evaluator = input()
        evaluator = int(evaluator)
        evaluator = self.evaluator_names[evaluator]
        plt.ion()
        if evaluator == "evaluator_SMLeadTunnelTimeByLeadScan":
            for i in range(n_repetitions):
                plt.figure(1)
                plt.plot(raw_measurement_positive_detune_pd[gate][evaluator][2 * i, :])
                plt.plot(raw_measurement_positive_detune_pd[gate][evaluator][2 * i + 1, :])
                plt.legend(["Data", "Background"])
                plt.draw()
                plt.pause(0.05)
                plt.figure(2)
                diff = raw_measurement_positive_detune_pd[gate][evaluator][2 * i + 1, :] - \
                       raw_measurement_positive_detune_pd[gate][evaluator][2 * i, :]
                #                plt.plot(diff)
                qtune.Evaluator.fit_lead_times(diff)
                plt.legend(["BG subtracted"])
                plt.pause(0.05)
                decision_continue = input("Type STOP to stop. Type anything else to continue.")
                if decision_continue == "STOP":
                    plt.close()
                    return
                else:
                    plt.close()
                    plt.figure(1)
                    plt.close()
            for i in range(n_repetitions):
                plt.figure(1)
                plt.plot(raw_measurement_negative_detune_pd[gate][evaluator][2 * i, :])
                plt.plot(raw_measurement_negative_detune_pd[gate][evaluator][2 * i + 1, :])
                plt.legend(["Data", "Background"])
                plt.draw()
                plt.pause(0.05)
                plt.figure(2)
                diff = raw_measurement_negative_detune_pd[gate][evaluator][2 * i + 1, :] - \
                       raw_measurement_negative_detune_pd[gate][evaluator][2 * i, :]
                #                plt.plot(diff)
                qtune.Evaluator.fit_lead_times(diff)
                #plt.legend(["BG subtracted"])
                plt.pause(0.05)
                decision_continue = input("Type STOP to stop. Type anything else to continue.")
                if decision_continue == "STOP":
                    plt.close()
                    return
                else:
                    plt.close()
                    plt.figure(1)
                    plt.close()
        elif evaluator == "evaluator_SMInterDotTCByLineScan":
            for i in range(n_repetitions):
                plt.figure(1)
                ydata = raw_measurement_positive_detune_pd[gate][evaluator][i, :]
                scan_range = delta_u
                npoints = len(ydata)
                center = 0. # TODO: change for real center
                qtune.Evaluator.fit_inter_dot_coupling(ydata=ydata, center=center, scan_range=scan_range, npoints=npoints)
                plt.pause(0.05)
                decision_continue = input("Type STOP to stop. Type anything else to continue.")
                if decision_continue == "STOP":
                    plt.close()
                    return
                else:
                    plt.close()
        else:
            print("No plotting implemented for this evaluator.")

    def load_evaluator_names(self, tune_run_number: int=1):
        tune_run_group = self.load_tune_run_group(tune_run_number=tune_run_number)
        if tune_run_group.__contains__("tune_sequence/step_0"):
            first_step_group = tune_run_group["tune_sequence/step_0"]
            list_evaluator_names = []
            for element in first_step_group:
                if isinstance(first_step_group[element], h5py.Dataset) and "evaluator_" in element:
                    list_evaluator_names += [element, ]
            self.evaluator_names = list_evaluator_names
        else:
            first_gradient_group = self.load_gradient_group(gradient_number=1, tune_run_number=tune_run_number)
            run_group = first_gradient_group["negative_detune_run_" + self.tunable_gate_names[0].decode("ascii") + "_0"]
            list_evaluator_names = []
            for element in run_group:
                if isinstance(run_group[element], h5py.Dataset) and "evaluator_" in element:
                    list_evaluator_names += [element, ]
            self.evaluator_names = list_evaluator_names
        return list_evaluator_names

    def load_raw_measurement_sequence_pd(self, start: int=0, end: int=None, tune_run_number: int=1):
        self.load_evaluator_names(tune_run_number=tune_run_number)
        tune_run_group = self.load_tune_run_group(tune_run_number=tune_run_number)
        sequence_group = tune_run_group["tune_sequence"]
        if end is None:
            end = count_steps_in_sequence(sequence_group)
        raw_measurement_sequence_pd = pd.DataFrame(index=self.evaluator_names, columns=range(start, end))
        for i in range(start, end):
            raw_measurement_pd, attribute_info_pd = self.load_raw_measurement_pd(sequence_group["step_" + str(i)])
            for evaluator in self.evaluator_names:
                raw_measurement_sequence_pd[i][evaluator] = raw_measurement_pd[evaluator]
        return raw_measurement_sequence_pd

    def plot_raw_measurement_tune_run(self, tune_run_number: int=1, start: int=0, end: int=None):
        self.load_evaluator_names(tune_run_number=tune_run_number)
        tune_run_group = self.load_tune_run_group(tune_run_number=tune_run_number)
        tune_sequence_group = tune_run_group["tune_sequence"]
        if end is None:
            end = count_steps_in_sequence(tune_sequence_group)
        raw_measurement_sequence_pd = self.load_raw_measurement_sequence_pd(start=start, end=end,
                                                                            tune_run_number=tune_run_number)
        plt.ion()
        for i in range(start, end):
            for evaluator in self.evaluator_names:
                plt.figure(1)
                plt.plot(raw_measurement_sequence_pd[i][evaluator])
                print(raw_measurement_sequence_pd[i][evaluator])
                plt.ylabel(evaluator)
                plt.pause(0.05)
                decision_continue = input("Type STOP to stop. Type anything else to continue.")
                if decision_continue == "STOP":
                    plt.close()
                    return
                else:
                    plt.close()

    def load_single_values_gradient_calculation(self, gradient_number: int = 1, tune_run_number: int = 0) -> (
            pd.Series, int, float):
        gradient_group = self.load_gradient_group(gradient_number=gradient_number, tune_run_number=tune_run_number)
        n_repetitions = gradient_group.attrs["n_repetitions"]
#        n_repetitions = gradient_group["n_repetitions"].value
        delta_u = gradient_group.attrs["delta_u"]
#        delta_u = gradient_group["delta_u"].value
        single_values_pd = pd.DataFrame(None, index=self.parameter_names, columns=self.tunable_gate_names)
        temp_parameter = pd.Series()
        for gate in self.tunable_gate_names:
            for parameter in self.parameter_names:
                single_values_pd[gate][parameter] = np.zeros((n_repetitions, 2))
            for i in range(n_repetitions):
                positive_run_group = gradient_group["positive_detune_run_" + gate.decode("ascii") + "_" + str(i)]
                for element in positive_run_group.keys():
                    if "evaluator_" in element:
                        for parameter_name in positive_run_group[element].attrs.keys():
                            if "parameter_" in parameter_name:
                                temp_parameter[parameter_name] = positive_run_group[element].attrs[parameter_name]
                temp_parameter = temp_parameter.sort_index()

                for parameter in self.parameter_names:
                    single_values_pd[gate][parameter][i, 0] = temp_parameter[parameter.decode("ascii")]

                negative_run_group = gradient_group["negative_detune_run_" + gate.decode("ascii") + "_" + str(i)]
                for element in negative_run_group.keys():
                    if "evaluator_" in element:
                        for parameter_name in negative_run_group[element].attrs.keys():
                            if "parameter_" in parameter_name:
                                temp_parameter[parameter_name] = negative_run_group[element].attrs[parameter_name]
                temp_parameter = temp_parameter.sort_index()
                for parameter in self.parameter_names:
                    single_values_pd[gate][parameter][i, 1] = temp_parameter[parameter.decode("ascii")]
        return single_values_pd, n_repetitions, delta_u

    def load_tune_run_group(self, tune_run_number) -> h5py.Group:
        if self.root_group.__contains__("tunerun_" + str(tune_run_number)):
            tune_run_group = self.root_group["tunerun_" + str(tune_run_number)]
            self.load_parameter_names(tune_run_number=tune_run_number)
        else:
            print("There is no tunerun number " + str(tune_run_number) + "in this file.")
            raise KeyError("Group does not exist.")
        return tune_run_group

    def load_gradient_group(self, gradient_number: int, tune_run_number: int) -> h5py.Group:
        tune_run_group = self.load_tune_run_group(tune_run_number)
        if not tune_run_group.__contains__("gradient_setup_" + str(gradient_number)):
            if tune_run_number > 0:
                print("There is no gradient saved for the gradient setup number " + str(
                    gradient_number) + " in tune run number" + str(
                    tune_run_number) + ".")
                decision = input("Would you like to load the gradient from the previous run? (Y/N)")
                if decision == "Y":
                    print("Gradient will be loaded from a previous run!")
                    return self.load_gradient_group(gradient_number, tune_run_number - 1)
                elif decision == "N":
                    print("No gradient could be loaded!")
                    raise KeyError("Group does not exist.")
                else:
                    print("This was a yes or no question. Answer with Y or N!")
                    return self.load_gradient_group(gradient_number=gradient_number, tune_run_number=tune_run_number)
            else:
                print("There is no gradient saved for the gradient setup number " + str(
                    gradient_number) + " in tune run number" + str(
                    tune_run_number) + ".")
                raise KeyError("Group does not exist.")
        gradient_group = tune_run_group["gradient_setup_" + str(gradient_number)]
        return gradient_group

    def logout(self):
        self.root_group.close()

    def compute_gradient_from_raw_data(self, fit_functions, evaluators, gradient_number: int = 1,
                                       tune_run_number: int = 0):
        raw_measurement_positive_detune_pd, raw_measurement_negative_detune_pd, n_repetitions, delta_u = \
            self.load_raw_measurement_gradient_calculation(gradient_number=gradient_number,
                                                           tune_run_number=tune_run_number)
        n_evaluators = len(evaluators)
        positive_detune = pd.DataFrame()
        negative_detune = pd.DataFrame()
        positive_detune_parameter = pd.Series()
        negative_detune_parameter = pd.Series()
        for gate in self.tunable_gate_names:
            for parameter in self.parameter_names:
                for i in range(n_repetitions):
                    for evaluator_number in range(n_evaluators):
                        raise NotImplementedError



def count_steps_in_sequence(sequence_group: h5py.Group):
    counter = 0
    for key in sequence_group.keys():
        if "step_" in key:
            counter += 1
    return counter


def load_gradient_from_group(data_group: h5py.Group):
    gradient = data_group['gradient'][:]
    heuristic_covariance = data_group['heuristic_covariance'][:]
    if "heuristic_noise" in data_group:
        heuristic_noise = data_group['heuristic_noise'][:]
    else:
        heuristic_noise = None
    return gradient, heuristic_covariance, heuristic_noise


def print_group_content(data_group: h5py.Group):
    print("Subgroups:")
    for element in data_group:
        if isinstance(data_group[element], h5py.Group):
            print(element)
    print("Datasets:")
    for element in data_group:
        if isinstance(data_group[element], h5py.Dataset):
            print(element)
    print("Attributes:")
    for element in data_group.attrs:
        print(element)
        print(data_group.attrs[element])
        print("\n")


def load_single_evaluation_from_group(data_group: h5py.Group, evaluator_name: str=None, evaluator_number: int =-1):
    if evaluator_name is None:
        if evaluator_number == -1:
            print("Please choose an evaluator. This can be done by name or from the Series of known evaluators.")
            raise ValueError
        evaluator_name = known_evaluators.index.tolist()[evaluator_number]

    evaluator_data_set = data_group[evaluator_name]
    raw_data = evaluator_data_set[:]
    parameters_pd = pd.Series()
    information_pd = pd.Series()
    for attribute in evaluator_data_set.attrs.keys():
        if "parameter_" in attribute:
            parameters_pd[attribute] = evaluator_data_set.attrs(attribute)
        else:
            information_pd[attribute] = evaluator_data_set.attrs(attribute)
    return raw_data, parameters_pd, information_pd


def fit_lead_times_old(ydata: np.ndarray):
    samprate = 1e8
    n_points = len(ydata)
    xdata = np.asarray([i for i in range(n_points)]) / samprate
    p0 = [ydata[round(1. / 4. * n_points)] - ydata[round(3. / 4. * n_points)],
          50e-9, 50e-9, 70e-9, 2070e-9, np.mean(ydata)]
    popt, pcov = optimize.curve_fit(f=func_lead_times, p0=p0, xdata=xdata, ydata=ydata)
    begin_lin = int(round(popt[4] / 10e-9))
    end_lin = begin_lin + 7
    slope = (ydata[end_lin] - ydata[begin_lin]) / (xdata[end_lin] - xdata[begin_lin])
    linear_offset = ydata[begin_lin] - xdata[begin_lin] * slope
    p0 += [slope, linear_offset, xdata[end_lin]]
    begin_lin_1 = int(round(popt[3] / 10e-9))
    end_lin_1 = begin_lin_1 + 7
    slope_1 = (ydata[end_lin_1] - ydata[begin_lin_1]) / (xdata[end_lin_1] - xdata[begin_lin_1])
    linear_offset_1 = ydata[begin_lin_1] - xdata[begin_lin_1] * slope_1
    p0 += [slope_1, linear_offset_1, xdata[end_lin_1]]
    plt.plot(xdata, ydata)
    plt.plot(xdata, func_lead_times_v2(xdata, p0[0], p0[1], p0[2], p0[3], p0[4], p0[5], p0[6], p0[7], p0[8], p0[9], p0[10], p0[11]))
    popt, pcov = optimize.curve_fit(f=func_lead_times_v2, p0=p0, xdata=xdata, ydata=ydata)
    plt.figure(6)
    plt.plot(xdata, ydata)
    plt.plot(xdata, func_lead_times_v2(xdata, popt[0], popt[1], popt[2], popt[3], popt[4], popt[5], popt[6], popt[7], popt[8], popt[9], popt[10], popt[11]))
    plt.pause(0.05)
    print("fit parameters")
    print(popt)
    return popt, pcov


def func_lead_times(x, hight: float, t_fall: float, t_rise: float, begin_rise: float, begin_fall: float,
                    offset: float):
    x = np.squeeze(x)
    n_points = len(x)
    y = np.zeros((n_points, ))
    for i in range(n_points):
        if x[i] >= begin_rise and x[i] <= begin_fall:
            c = np.cosh(.5*begin_fall/t_rise)
            s = np.sinh(.5*begin_fall/t_rise)
            e = np.exp(.5*(begin_fall - 2. * x[i]) / t_rise)
            signed_hight = hight
        elif x[i] < begin_rise:
            c = np.cosh(.5*begin_fall/t_fall)
            s = np.sinh(.5*begin_fall/t_fall)
            e = np.exp(.5*(1. * begin_fall - 2. * (x[i] + x[n_points - 1])) / t_fall)
            signed_hight = -1. * hight
        else:
            c = np.cosh(.5*begin_fall/t_fall)
            s = np.sinh(.5*begin_fall/t_fall)
            e = np.exp(.5*(3. * begin_fall - 2. * x[i]) / t_fall)
            signed_hight = -1. * hight
        y[i] = offset + .5 * signed_hight * (c - e) / s
    return y


