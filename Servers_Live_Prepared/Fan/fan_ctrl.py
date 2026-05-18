#!/usr/bin/python
# -*- coding: utf-8 -*-

import RPi.GPIO as GPIO
import time
import sys

# Configuration
FAN_PIN = 14  # BCM pin for the fan control
WAIT_TIME = 1  # [s] Delay between temperature checks
PWM_FREQ = 10  # [Hz] Adjust if the fan behaves strangely

# Speed range for fan control
FAN_MIN = 80  # [%] Minimum fan speed when operating
FAN_MAX = 100  # [%] Maximum fan speed

# Temperature range for fan control
TEMP_MIN = 30  # [°C] Temperature where fan starts at minimum speed
TEMP_MAX = 80  # [°C] Temperature where fan reaches max speed

# Hysteresis to prevent constant speed changes
HYSTERESIS = 1  # [°C]

# Setup GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(FAN_PIN, GPIO.OUT, initial=GPIO.LOW)
fan = GPIO.PWM(FAN_PIN, PWM_FREQ)
fan.start(0)

cpuTempOld = 0
fanSpeedOld = 0

while True:
    # Read CPU temperature
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as cpuTempFile:
        cpuTemp = float(cpuTempFile.read()) / 1000  # Convert from millidegrees

    # Check if temperature change is significant enough to update speed
    if abs(cpuTemp - cpuTempOld) > HYSTERESIS:
        # If below TEMP_MIN, keep fan at minimum speed
        if cpuTemp <= TEMP_MIN:
            fanSpeed = FAN_MIN
        # If above TEMP_MAX, run fan at full speed
        elif cpuTemp >= TEMP_MAX:
            fanSpeed = FAN_MAX
        # Linearly interpolate fan speed between TEMP_MIN and TEMP_MAX
        else:
            fanSpeed = round(FAN_MIN + (cpuTemp - TEMP_MIN) * (FAN_MAX - FAN_MIN) / (TEMP_MAX - TEMP_MIN), 1)

        # Update fan speed only if there's a change
        if fanSpeed != fanSpeedOld:
            fan.ChangeDutyCycle(fanSpeed)
            fanSpeedOld = fanSpeed

        cpuTempOld = cpuTemp  # Store last temperature

    # Wait before next temperature check
    time.sleep(WAIT_TIME)