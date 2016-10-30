#!/usr/bin/env python3

"""
Usage:
    rotate.py [options]

Options:
    -h,--help        display help message
    --version        display version and exit
"""

import dbus, sys, time, subprocess, socket, logging, docopt, multiprocessing, io, os, signal
from gi.repository import GLib
from dbus.mainloop.glib import DBusGMainLoop

name    = "thinkpad_x1_yoga_rotation"
version = "0.9-SNAPSHOT"

# map sensor-proxy orientation to xrandr and wacom
# there seems to be a bug:
# 'right-up' when laptop has normal orientation
# 'normal' for 90 left
# 'bottom-up' for 90 right
# 'left-up' for 180
xrandr_orientation_map = {
    'right-up': 'normal',
    'normal' : 'right',
    'bottom-up': 'left',
    'left-up': 'inverted'
}

wacom_orientation_map = {
    'right-up': 'none',
    'normal' : 'cw',
    'bottom-up': 'ccw',
    'left-up': 'half'
}

def cmd_and_log(cmd):
    exit = subprocess.call(cmd)
    log.info("running %s with exit code %s", cmd, exit)

def sensor_proxy_signal_handler(source, changedProperties, invalidatedProperties, **kwargs):
    if source=='net.hadess.SensorProxy':
        if 'AccelerometerOrientation' in changedProperties:
            orientation = changedProperties['AccelerometerOrientation']
            log.info("dbus signal indicates orientation change to %s", orientation)
            subprocess.call(["xrandr", "-o", xrandr_orientation_map[orientation]])
            for device in wacom:
                cmd_and_log(["xsetwacom", "set", device, "rotate", wacom_orientation_map[orientation]])

# toggle trackpoint and touchpad when changing from laptop to tablet mode anc vice versa
def monitor_acpi_events():
    socketACPI = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    socketACPI.connect("/var/run/acpid.socket")

    lines = subprocess.check_output(['xinput','--list', '--name-only']).split(b'\n')
    touch_and_track = [x.decode() for x in lines if b"TrackPoint" in x or b"TouchPad" in x]
    log.info("found touchpad and trackpoints %s", touch_and_track)

    is_laptop_mode = True
    log.info("connected to acpi socket %s", socket)
    onboard_pid = None
    while True:
        event = socketACPI.recv(4096)
        log.debug("catching acpi event %s", event) 
        #eventACPIDisplayPositionChange = "ibm/hotkey LEN0068:00 00000080 000060c0\n"
        eventACPIDisplayPositionChange = b" PNP0C14:03 000000b0 00000000\n"
        if event == eventACPIDisplayPositionChange:
            is_laptop_mode = not is_laptop_mode
            log.info("display position change detected, laptop mode %s", is_laptop_mode)
            if is_laptop_mode:
                for x in touch_and_track:
                    cmd_and_log(["xinput", "--enable", x])
                if onboard_pid:
                    os.kill(onboard_pid, signal.SIGTERM)
            else:
                for x in touch_and_track:
                    cmd_and_log(["xinput", "--disable", x])
                p = subprocess.Popen(['nohup', 'onboard'],
                    stdout=open('/dev/null', 'w'),
                    #stderr=open('logfile.log', 'a'),
                    preexec_fn=os.setpgrp
                ) 
                onboard_pid = p.pid
                log.info("started onboard with pid %s", onboard_pid)
        time.sleep(0.3)

def monitor_stylus_proximity():
    lines = subprocess.check_output(['xinput','--list', '--name-only']).decode().split('\n')
    stylus = next(x for x in lines if "stylus" in x)
    log.info("found stylus %s", stylus)
    finger_touch = next(x for x in lines if "Finger touch" in x)
    log.info("found finger touch %s", finger_touch)
    out = subprocess.Popen(["xinput", "test", "-proximity", stylus], stdout=subprocess.PIPE)
    for line in out.stdout:
        if (line.startswith(b'proximity')):
            log.debug(line)
            status = line.split(b' ')[1]
            cmd_and_log(["xinput", "--disable" if status==b'in' else "--enable", finger_touch])

def main(options):

    # logging
    global log
    log        = logging.getLogger()
    logHandler = logging.StreamHandler()
    log.addHandler(logHandler)
    logHandler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    log.level  = logging.INFO

    # load wacom devices 
    lines = subprocess.check_output(['xsetwacom','--list', 'devices']).split(b'\n')
    global wacom 
    wacom = [ x.decode().split('\t')[0] for x in lines if x]
    log.info("detected wacom devices: %s", wacom)

    # listen for ACPI events to detect switching between laptop/tablet mode
    acpi_process = multiprocessing.Process(target = monitor_acpi_events)
    acpi_process.start()

    proximity_process = multiprocessing.Process(target = monitor_stylus_proximity)
    proximity_process.start()

    # init dbus stuff and subscribe to events
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    proxy = bus.get_object('net.hadess.SensorProxy', '/net/hadess/SensorProxy')
    props = dbus.Interface(proxy, 'org.freedesktop.DBus.Properties')
    props.connect_to_signal('PropertiesChanged', sensor_proxy_signal_handler, sender_keyword='sender')
    iface = dbus.Interface(proxy, 'net.hadess.SensorProxy')
    iface.ClaimAccelerometer()
    #iface.ClaimLight()

    loop = GLib.MainLoop()
    loop.run()

if __name__ == "__main__":
    options = docopt.docopt(__doc__)
    if options["--version"]:
        print(version)
        exit()
    main(options)