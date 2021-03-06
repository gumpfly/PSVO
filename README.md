# PSVO: Particle Smoothing Variational Objectives

This code provides a reference implementation of the algorithm Smoothing Variational Objectives (SVO) described in the publications: 

* Moretti, A.\*, Wang, Z.\*, Wu, L.\*, Drori, I., Pe'er, I. [Particle Smoothing Variational Objectives](https://arxiv.org/abs/1909.09734). arXiv preprint, 2019.

* Moretti, A.\*, Wang, Z.\*, Wu, L., Pe'er, I. [Smoothing Nonlinear Variational Objectives with Sequential Monte Carlo](https://openreview.net/pdf?id=HJg24U8tuE). ICLR Workshop on Deep Generative Models for Highly Structured Data, 2019.

SVO is written as an abstract class that reduces to two related variational inference methods for time series. As a reference, the AESMC and IWAE algorithms are implemented from the following publications:

* Le, T., Igl, M., Rainforth, T., Jin, T., Wood, F. [Auto-Encoding Sequential Monte Carlo](https://arxiv.org/abs/1705.10306). ICLR, 2018.

* Burda, Y., Grosse, R., Salakhutidinov, R. [Importance Weighted Autoencoders](https://arxiv.org/abs/1509.00519). ICLR, 2016.


## Installation

The code is written in Python 3.6. The following dependencies are required:

* Tensorflow
* seaborn
* numpy
* scipy 
* matplotlib

To check out, run `git@github.com:amoretti86/psvo.git`


## Usage

Running `python runner_flags.py` will find a two dimensional representation of the Fitzhugh-Nagumo dynamical system from one dimensional observations. The following figure provides the original dynamical system and trajectories along with the resulting inferred dynamics and trajectories from SVO. 

## Demo

| Original | Inferred |
|:--------------------------:|:--------------------------:|
|![fhn](https://github.com/amoretti86/PSVO/blob/master/data/fhn/fhn.png)|![fit](https://github.com/amoretti86/PSVO/blob/master/data/fhn/fit.png)|


