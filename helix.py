import BlynkLib
import config
import machine
from machine import Pin
from machine import WDT
from machine import RTC
from network import WLAN

WIFI_SSID  = config.ssid
WIFI_AUTH  = config.auth
BLYNK_AUTH = config.token

MAIN_TASK_PERIOD = const(50)
WDT_TIMEOUT = const(15000)

COIN_INPUTS = {1:'GP16', 2:'GP15', 3:'GP22', 4:'GP17', 5:'GP12', 6:'GP11', 7:'GP14'}

def connect_to_wlan(wlan):
    # try connecting to wifi until succeeding
    while True:
        try:
            wlan.connect(WIFI_SSID, auth=WIFI_AUTH, timeout=7500)
            while not wlan.isconnected():
                machine.idle()
            return
        except OSError:
            pass

class PulseCounter:
    def __init__(self, pin, value=0):     # value is in cents
        self.pin = Pin(pin, mode=Pin.IN)
        self.value = value
        self.count = 0
        self.total = 0
        self.int = self.pin.irq(handler=self._count, trigger=Pin.IRQ_FALLING, priority=7)

    def _count(self, pin):
        self.count += 1
        self.total += self.value

class LedShow:
    values = ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1), 
              (0, 0, 1, 0), (0, 1, 0, 0), (1, 0, 0, 0), (1, 1, 1, 1))

    LEDS_SWEEP_TIME = const(50)

    def __init__(self, pin1, pin2, pin3, pin4, period=50):
        self.leds = []
        self.leds.append(Pin(pin1, mode=Pin.OUT, drive=Pin.MED_POWER, value=1))
        self.leds.append(Pin(pin2, mode=Pin.OUT, drive=Pin.MED_POWER, value=1))
        self.leds.append(Pin(pin3, mode=Pin.OUT, drive=Pin.MED_POWER, value=1))
        self.leds.append(Pin(pin4, mode=Pin.OUT, drive=Pin.MED_POWER, value=1))
        self.period = 50
        self.mode = 'IDLE'
        self.state = 0
        self.time = 0

    def _set_leds(self, value):
        for i in range(len(self.leds)):
            self.leds[i](value[i])

    def run(self):
        self.time += self.period
        if self.time >= LEDS_SWEEP_TIME:
            self.time = 0
            if self.mode == 'IDLE':
                pass
            elif self.mode == 'COIN_IN':
                self._set_leds(self.values[self.state])
                self.state += 1
                if self.state >= len(self.values):
                    self.mode = 'IDLE'
                    self.state = 0

    def coin_in(self):
        self.mode = 'COIN_IN'
        self.state = 0

    def alarm(self):
        self.mode = 'ALARM'
        self.state = 0

    def coin_out(self):
        self.mode = 'COIN_OUT'
        self.state = 0

class MainTask:
    MAX_UPDATE_PERIOD = const(2000)

    def __init__(self, blynk, wdt, period, c10cent, c20cent, c50cent, c1eur, c2eur, euros, alarm):
        self.blynk = blynk
        self.wdt = wdt
        self.period = period
        self.leds = LedShow('GP7', 'GP8', 'GP9', 'GP10', period)
        self.time = 0
        self.euros = PulseCounter(euros)
        self.alarm = PulseCounter(alarm)
        self.prev_coins = [0, 0]
        self.coins = [PulseCounter(c10cent, 10),
                      PulseCounter(c20cent, 20),
                      PulseCounter(c50cent, 50),
                      PulseCounter(c1eur, 100),
                      PulseCounter(c2eur, 200)]

    def _send_coins(self):
            self.blynk.virtual_write(1, self.coins[2].count) # 50 cent
            self.blynk.virtual_write(2, self.coins[3].count) # 1 EUR
            self.blynk.virtual_write(3, self.coins[2].count + self.coins[3].count) # total
            eur_in = (self.coins[2].count * self.coins[2].value) + (self.coins[3].count * self.coins[3].value)
            seur_in = '{:d}'.format(eur_in // 100) + '.' + '{:02d}'.format(eur_in % 100)
            self.blynk.virtual_write(4, seur_in) # cash balance
            self.blynk.virtual_write(5, seur_in)
            self.blynk.virtual_write(6, 0) # EUR out

    def run(self):
        # feed the watchdog
        self.wdt.feed()
        # run the LEDs task
        self.leds.run()

        self.time += self.period
        if self.time >= MAX_UPDATE_PERIOD:
            self.blynk.lcd_write(0, 0, 0, "Customer:       ")
            self.blynk.lcd_write(0, 0, 1, config.CUSTOMER)
            self.blynk.lcd_write(7, 0, 0, "Serial:         ")
            self.blynk.lcd_write(7, 0, 1, config.SERIAL)
            self._send_coins()
            self.time = 0

        c_coins =[self.coins[2].count, self.coins[3].count]
        if self.prev_coins != c_coins:
            self.prev_coins = c_coins
            self.leds.coin_in()
            self._send_coins()

wdt = WDT(timeout=WDT_TIMEOUT)

wlan = WLAN(mode=WLAN.STA)
connect_to_wlan(wlan) # the WDT will reset if this takes more than 15s

wdt.feed()

# set the current time (mandatory to validate certificates)
RTC(datetime=(2015, 12, 12, 11, 30, 0, 0, None))

# initialize Blynk with SSL enabled
blynk = BlynkLib.Blynk(BLYNK_AUTH, wdt=False, ssl=True)

# register the main task
s_task = MainTask(blynk, wdt, MAIN_TASK_PERIOD, COIN_INPUTS[config.COIN_10_CENT],
                                                COIN_INPUTS[config.COIN_20_CENT],
                                                COIN_INPUTS[config.COIN_50_CENT],
                                                COIN_INPUTS[config.COIN_1_EUR],
                                                COIN_INPUTS[config.COIN_2_EUR],
                                                COIN_INPUTS[config.EUR_TOTAL],
                                                COIN_INPUTS[config.ALARM])
blynk.set_user_task(s_task.run, MAIN_TASK_PERIOD)

while True:
    wdt.feed()
    try:
        blynk.run()
    except MemoryError:
        machine.reset()
    except Exception as e:
        print(repr(e))
        if not wlan.isconnected():
            connect_to_wlan(wlan)
