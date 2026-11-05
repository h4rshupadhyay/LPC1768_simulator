"""LPC1768 LQFP100 pin functions, UM10360 tables 79-85 (PINSEL0-PINSEL10).

Each entry lists the names selected by PINSEL values 0-3. Function 0 is GPIO.
Pad electrical classes follow the data sheet pad notes: 5 V tolerant digital
pads; ADC/DAC pads that lose 5 V tolerance in analog mode; the open-drain I2C0
pads; and the USB D+/D- pads, which are never 5 V tolerant.
"""
from __future__ import annotations

_ = None
FUNCTIONS: dict[tuple[int, int], tuple] = {
    (0, 0): ('P0.0', 'RD1', 'TXD3', 'SDA1'),
    (0, 1): ('P0.1', 'TD1', 'RXD3', 'SCL1'),
    (0, 2): ('P0.2', 'TXD0', 'AD0.7', _),
    (0, 3): ('P0.3', 'RXD0', 'AD0.6', _),
    (0, 4): ('P0.4', 'I2SRX_CLK', 'RD2', 'CAP2.0'),
    (0, 5): ('P0.5', 'I2SRX_WS', 'TD2', 'CAP2.1'),
    (0, 6): ('P0.6', 'I2SRX_SDA', 'SSEL1', 'MAT2.0'),
    (0, 7): ('P0.7', 'I2STX_CLK', 'SCK1', 'MAT2.1'),
    (0, 8): ('P0.8', 'I2STX_WS', 'MISO1', 'MAT2.2'),
    (0, 9): ('P0.9', 'I2STX_SDA', 'MOSI1', 'MAT2.3'),
    (0, 10): ('P0.10', 'TXD2', 'SDA2', 'MAT3.0'),
    (0, 11): ('P0.11', 'RXD2', 'SCL2', 'MAT3.1'),
    (0, 15): ('P0.15', 'TXD1', 'SCK0', 'SCK'),
    (0, 16): ('P0.16', 'RXD1', 'SSEL0', 'SSEL'),
    (0, 17): ('P0.17', 'CTS1', 'MISO0', 'MISO'),
    (0, 18): ('P0.18', 'DCD1', 'MOSI0', 'MOSI'),
    (0, 19): ('P0.19', 'DSR1', _, 'SDA1'),
    (0, 20): ('P0.20', 'DTR1', _, 'SCL1'),
    (0, 21): ('P0.21', 'RI1', _, 'RD1'),
    (0, 22): ('P0.22', 'RTS1', _, 'TD1'),
    (0, 23): ('P0.23', 'AD0.0', 'I2SRX_CLK', 'CAP3.0'),
    (0, 24): ('P0.24', 'AD0.1', 'I2SRX_WS', 'CAP3.1'),
    (0, 25): ('P0.25', 'AD0.2', 'I2SRX_SDA', 'TXD3'),
    (0, 26): ('P0.26', 'AD0.3', 'AOUT', 'RXD3'),
    (0, 27): ('P0.27', 'SDA0', 'USB_SDA', _),
    (0, 28): ('P0.28', 'SCL0', 'USB_SCL', _),
    (0, 29): ('P0.29', 'USB_D+', _, _),
    (0, 30): ('P0.30', 'USB_D-', _, _),
    (1, 0): ('P1.0', 'ENET_TXD0', _, _),
    (1, 1): ('P1.1', 'ENET_TXD1', _, _),
    (1, 4): ('P1.4', 'ENET_TX_EN', _, _),
    (1, 8): ('P1.8', 'ENET_CRS', _, _),
    (1, 9): ('P1.9', 'ENET_RXD0', _, _),
    (1, 10): ('P1.10', 'ENET_RXD1', _, _),
    (1, 14): ('P1.14', 'ENET_RX_ER', _, _),
    (1, 15): ('P1.15', 'ENET_REF_CLK', _, _),
    (1, 16): ('P1.16', 'ENET_MDC', _, _),
    (1, 17): ('P1.17', 'ENET_MDIO', _, _),
    (1, 18): ('P1.18', 'USB_UP_LED', 'PWM1.1', 'CAP1.0'),
    (1, 19): ('P1.19', 'MCOA0', 'USB_PPWR', 'CAP1.1'),
    (1, 20): ('P1.20', 'MCI0', 'PWM1.2', 'SCK0'),
    (1, 21): ('P1.21', 'MCABORT', 'PWM1.3', 'SSEL0'),
    (1, 22): ('P1.22', 'MCOB0', 'USB_PWRD', 'MAT1.0'),
    (1, 23): ('P1.23', 'MCI1', 'PWM1.4', 'MISO0'),
    (1, 24): ('P1.24', 'MCI2', 'PWM1.5', 'MOSI0'),
    (1, 25): ('P1.25', 'MCOA1', _, 'MAT1.1'),
    (1, 26): ('P1.26', 'MCOB1', 'PWM1.6', 'CAP0.0'),
    (1, 27): ('P1.27', 'CLKOUT', 'USB_OVRCR', 'CAP0.1'),
    (1, 28): ('P1.28', 'MCOA2', 'PCAP1.0', 'MAT0.0'),
    (1, 29): ('P1.29', 'MCOB2', 'PCAP1.1', 'MAT0.1'),
    (1, 30): ('P1.30', _, 'VBUS', 'AD0.4'),
    (1, 31): ('P1.31', _, 'SCK1', 'AD0.5'),
    (2, 0): ('P2.0', 'PWM1.1', 'TXD1', _),
    (2, 1): ('P2.1', 'PWM1.2', 'RXD1', _),
    (2, 2): ('P2.2', 'PWM1.3', 'CTS1', _),
    (2, 3): ('P2.3', 'PWM1.4', 'DCD1', _),
    (2, 4): ('P2.4', 'PWM1.5', 'DSR1', _),
    (2, 5): ('P2.5', 'PWM1.6', 'DTR1', _),
    (2, 6): ('P2.6', 'PCAP1.0', 'RI1', _),
    (2, 7): ('P2.7', 'RD2', 'RTS1', _),
    (2, 8): ('P2.8', 'TD2', 'TXD2', 'ENET_MDC'),
    (2, 9): ('P2.9', 'USB_CONNECT', 'RXD2', 'ENET_MDIO'),
    (2, 10): ('P2.10', 'EINT0', 'NMI', _),
    (2, 11): ('P2.11', 'EINT1', _, 'I2STX_CLK'),
    (2, 12): ('P2.12', 'EINT2', _, 'I2STX_WS'),
    (2, 13): ('P2.13', 'EINT3', _, 'I2STX_SDA'),
    (3, 25): ('P3.25', _, 'MAT0.0', 'PWM1.2'),
    (3, 26): ('P3.26', 'STCLK', 'MAT0.1', 'PWM1.3'),
    (4, 28): ('P4.28', 'RX_MCLK', 'MAT2.0', 'TXD3'),
    (4, 29): ('P4.29', 'TX_MCLK', 'MAT2.1', 'RXD3'),
}

# signal name -> [(port, pin, PINSEL value)]
SIGNALS: dict[str, list[tuple[int, int, int]]] = {}
for (_port, _pin), _names in FUNCTIONS.items():
    for _function, _name in enumerate(_names[1:], start=1):
        if _name:
            SIGNALS.setdefault(_name, []).append((_port, _pin, _function))

ADC_PADS = {int(name[4]): pads[0] for name, pads in SIGNALS.items() if name.startswith('AD0.')}
OPEN_DRAIN_I2C = {(0, 27), (0, 28)}
USB_PADS = {(0, 29), (0, 30)}


def exists(port: int, pin: int) -> bool:
    return (port, pin) in FUNCTIONS


def name(port: int, pin: int, function: int) -> str | None:
    names = FUNCTIONS.get((port, pin))
    return names[function] if names else None


def pads_for(signal: str) -> list[tuple[int, int, int]]:
    return SIGNALS.get(signal, [])


def pad_class(port: int, pin: int, function: int) -> dict:
    """Electrical limits of a pad in its selected function (data sheet Tables 6, 8)."""
    selected = name(port, pin, function) or ''
    analog = selected.startswith('AD0.') or selected == 'AOUT'
    if (port, pin) in USB_PADS:
        return {'kind': 'usb', 'vmax': 3.6, 'vabs': 3.6, 'tolerant5v': False}
    if analog:
        # Analog-mode pads are not 5 V tolerant: operate 0..VDDA, VIA <= 5.1 V.
        return {'kind': 'analog', 'vmax': 3.3, 'vabs': 5.1, 'tolerant5v': False}
    if (port, pin) in OPEN_DRAIN_I2C:
        return {'kind': 'open-drain', 'vmax': 5.0, 'vabs': 5.5, 'tolerant5v': True}
    return {'kind': 'digital', 'vmax': 5.0, 'vabs': 5.5, 'tolerant5v': True}
