import itertools
import datetime
from typing import Iterable, Any, Callable, List
import numpy as np


__all__ = ['nth']


def nth(iterable: Iterable[Any], n: int) -> Any:
    """Returns the nth item or a default value"""
    return next(itertools.islice(iterable, n, None))


def static_vars(**kwargs) -> Callable[[Callable], Callable]:
    def decorate(func: Callable) -> Callable:
        for key, value in kwargs.items():
            setattr(func, key, value)
        return func
    return decorate


def time_string() -> str:
    return datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S')


def find_lead_transition(data: np.ndarray, center: float, scan_range: float, npoints: int, width: float = .2e-3) -> float:
    if len(data.shape) == 2:
        y = np.mean(data, 0)
    elif len(data.shape) == 1:
        y = data
    else:
        print('data must be a one or two dimensional array!')
        return np.nan

    x = np.linspace(center - scan_range, center + scan_range, npoints)

    n = int(width/scan_range*npoints)
    for i in range(0, len(y)-n-1):
        y[i] -= y[i+n]

    y_red = y[0:len(y) - n - 1]
    x_red = x[0:len(y) - n - 1]

    y_red = np.absolute(y_red)
    max_index = int(np.argmax(y_red) + int(round(n / 2)))

    return x[max_index]


def nth_diff(data:np.ndarray, n: int):
    data_diff = np.ndarray((len(data) - n, ))
    for i in range(0, len(data) - n):
        data_diff[i] = data[i] - data[i+n]
    return data_diff


def moving_average_filter(data: np.ndarray, width) -> np.ndarray:
    data = data.squeeze()
    n_points = data.size
    smoothed = np.zeros((n_points, ))
    for i in range(width):
        smoothed[i] = sum(data[0:i + 1])
        smoothed[i] *= 1. / float(i + 1)
    for i in range(width, n_points, 1):
        smoothed[i] = sum(data[i - width + 1:i + 1])
        smoothed[i] *= 1. / width
    return smoothed


def find_stepes_point_sensing_dot(data: np.ndarray, scan_range=5e-3, npoints=1280) -> float:
    data = moving_average_filter(data, 200)
    data = nth_diff(data, 30)
    data = moving_average_filter(data, 30)
    max_index = np.argmin(data) + 15
    detuning = (float(max_index) - float(npoints) / 2.) * scan_range / (float(npoints) / 2.)
    return detuning


#def gradient_min_evaluations(parameters: List(np.ndarray, ...), voltage_points: List(np.ndarray, ...)):
def gradient_min_evaluations(parameters, voltage_points):

    """
    Uses finite differences and basis transformations to compute the gradient.
    :param parameters: A list of paramters belonging to the voltages
    :param voltage_points: List of voltage points. Either
    :return:
    """
    n_points = len(voltage_points)
    assert(len(voltage_points) == len(parameters))
    n_parameters = parameters[0].size
    n_gates = voltage_points[0].size
    voltage_diff = np.zeros((n_gates, n_gates))
    parameter_diff = np.zeros((n_parameters, n_gates))

    if n_points == n_gates + 1:
        for i in range(1, n_points):
            voltage_diff[:][i - 1] = voltage_points[i] - voltage_points[0]
            parameter_diff[:][i - 1] = parameters[i] - parameters[0]
    elif n_points == 2 * n_gates:
        for i in range(n_gates):
            voltage_diff[:][i] = voltage_points[2 * i + 1] - voltage_points[2 * i]
            parameter_diff[:][i] = parameters[2 * i + 1] - parameters[2 * i]

    gradient = np.dot(parameter_diff, np.linalg.inv(voltage_diff))
    return gradient

