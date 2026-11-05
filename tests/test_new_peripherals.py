"""Compiled firmware exercising the peripherals added for external components."""
import functools
import struct

import pytest

from simulator.compiler import Compiler
from simulator.engine import Machine
from simulator.terminal import Terminal

MAILBOX = 0x10007000


@functools.lru_cache(maxsize=None)
def build(body):
    return Compiler().compile('#include <LPC17xx.h>\n' + body).hex


def machine(body, target='bare', **kwargs):
    return Machine(build(body), target=target, **kwargs)


def mailbox(m, count=4):
    return struct.unpack(f'<{count}I', bytes(m.uc.mem_read(MAILBOX, 4 * count)))


def run_until(m, condition, slices=400, step=20000):
    for _ in range(slices):
        m.run(step)
        if condition():
            return True
    return False


UART_ECHO = r'''
volatile unsigned *box = (volatile unsigned *)0x10007000;
void uart_init(unsigned baud) {
  LPC_PINCON->PINSEL0 = (LPC_PINCON->PINSEL0 & ~0xF0u) | 0x50u;  /* P0.2 TXD0, P0.3 RXD0 */
  LPC_UART0->LCR = 0x83;
  unsigned div = SystemCoreClock / 4 / 16 / baud;  /* PCLK = CCLK/4 */
  LPC_UART0->DLL = div & 0xFF; LPC_UART0->DLM = div >> 8;
  LPC_UART0->LCR = 0x03; LPC_UART0->FCR = 0x07;
}
void put(char c) { while (!(LPC_UART0->LSR & 0x20)) {} LPC_UART0->THR = c; }
int main(void) {
  uart_init(BAUD);
  const char *s = "Hi\r\n"; while (*s) put(*s++);
  box[3] = 0xC0DE;
  while (1) {
    if (LPC_UART0->LSR & 1) { char c = LPC_UART0->RBR; box[0]++; box[1] = c; put(c + 1); }
  }
}
'''


@pytest.mark.parametrize('baud', [9600, 38400])
def test_uart_transmits_to_terminal_and_echoes_received_bytes(baud):
    m = machine(f'#define BAUD {baud}\n' + UART_ECHO, target='mbed')
    terminal = Terminal('pc', baud, 0)
    m.terminals = {0: terminal}
    assert run_until(m, lambda: ''.join(terminal.text).endswith('Hi\r\n'), slices=4000)
    assert not terminal.mismatch
    uart = m.uarts[0]
    terminal.send(m, b'A', lambda b: uart.receive(b, terminal.baud))
    assert run_until(m, lambda: mailbox(m)[0] == 1, slices=4000)
    assert mailbox(m)[1] == ord('A')
    assert run_until(m, lambda: ''.join(terminal.text).endswith('B'), slices=4000)


def test_uart_baud_mismatch_garbles_and_explains():
    m = machine('#define BAUD 9600\n' + UART_ECHO, target='mbed')
    terminal = Terminal('pc', 115200, 0)
    m.terminals = {0: terminal}
    assert run_until(m, lambda: terminal.received >= 4, slices=4000)
    assert terminal.mismatch and ''.join(terminal.text) != 'Hi\r\n'
    m.uarts[0].receive(ord('x'), 115200, sender='PC terminal')
    assert 'UART0:baud' in m.notes and '115200' in m.notes['UART0:baud']


def test_uart_without_pinsel_reports_missing_pin():
    m = machine(r'''int main(void) {
      LPC_UART0->LCR = 0x83; LPC_UART0->DLL = 6; LPC_UART0->LCR = 3;
      LPC_UART0->THR = 'x'; while (1) {} }''')
    run_until(m, lambda: 'UART0:pin' in m.notes, slices=200)
    assert 'PINSEL' in m.notes['UART0:pin']


def test_unpowered_uart2_is_ignored_with_note():
    m = machine(r'''int main(void) { LPC_UART2->LCR = 0x83; while (1) {} }''')
    run_until(m, lambda: 'UART2:power' in m.notes, slices=50)
    assert 'PCONP bit 24' in m.notes['UART2:power']


SPI_MCP3008 = r'''
volatile unsigned *box = (volatile unsigned *)0x10007000;
unsigned xfer(unsigned v) { LPC_SSP0->DR = v; while (LPC_SSP0->SR & 0x10) {} while (!(LPC_SSP0->SR & 4)) {} return LPC_SSP0->DR; }
int main(void) {
  LPC_SC->PCONP |= 1u << 21;
  LPC_PINCON->PINSEL0 |= 2u << 30;            /* P0.15 SCK0 */
  LPC_PINCON->PINSEL1 |= (2u << 2) | (2u << 4); /* P0.17 MISO0, P0.18 MOSI0 */
  LPC_GPIO0->FIODIR |= 1u << 16; LPC_GPIO0->FIOSET = 1u << 16;  /* CS on P0.16 */
  LPC_SSP0->CR0 = 7; LPC_SSP0->CPSR = 8; LPC_SSP0->CR1 = 2;
  while (1) {
    LPC_GPIO0->FIOCLR = 1u << 16;
    xfer(0x01); unsigned hi = xfer(0x80 | (2 << 4)); unsigned lo = xfer(0);
    LPC_GPIO0->FIOSET = 1u << 16;
    box[0] = ((hi & 3) << 8) | lo; box[1]++;
  }
}
'''


def test_ssp_reads_mcp3008_channel_from_a_divider():
    m = machine(SPI_MCP3008)
    c = m.board.circuit
    c.add_part('mcp3008', 'adc')
    c.add_part('potentiometer', 'pot')
    for a, b in [('adc.VDD', 'mcu.3V3'), ('adc.VREF', 'mcu.3V3'), ('adc.AGND', 'mcu.GND'), ('adc.DGND', 'mcu.GND'),
                 ('adc.CLK', 'mcu.P0.15'), ('adc.CS', 'mcu.P0.16'), ('adc.DOUT', 'mcu.P0.17'), ('adc.DIN', 'mcu.P0.18'),
                 ('pot.1', 'mcu.3V3'), ('pot.3', 'mcu.GND'), ('pot.W', 'adc.CH2')]:
        c.connect(a, b)
    c.set_stimulus('pot', 'position', 0.25)
    assert run_until(m, lambda: mailbox(m)[1] >= 2, slices=2000)
    # Wiper 25% of the way from pin 1 (3.3 V): 75% of VREF.
    assert mailbox(m)[0] == pytest.approx(767, abs=3)


I2C_BMP = r'''
volatile unsigned *box = (volatile unsigned *)0x10007000;
void wait(void) { while (!(LPC_I2C0->I2CONSET & 8)) {} }
unsigned read_reg(unsigned reg) {
  LPC_I2C0->I2CONSET = 0x20; wait(); LPC_I2C0->I2CONCLR = 0x20;
  LPC_I2C0->I2DAT = 0x76 << 1; LPC_I2C0->I2CONCLR = 8; wait();
  if (LPC_I2C0->I2STAT != 0x18) { box[2] = LPC_I2C0->I2STAT; LPC_I2C0->I2CONSET = 0x10; LPC_I2C0->I2CONCLR = 8; return 0xFFFF; }
  LPC_I2C0->I2DAT = reg; LPC_I2C0->I2CONCLR = 8; wait();
  LPC_I2C0->I2CONSET = 0x20; LPC_I2C0->I2CONCLR = 8; wait(); LPC_I2C0->I2CONCLR = 0x20;
  LPC_I2C0->I2DAT = (0x76 << 1) | 1; LPC_I2C0->I2CONCLR = 8; wait();
  LPC_I2C0->I2CONCLR = 4 | 8; wait();
  unsigned v = LPC_I2C0->I2DAT;
  LPC_I2C0->I2CONSET = 0x10; LPC_I2C0->I2CONCLR = 8;
  return v;
}
int main(void) {
  LPC_PINCON->PINSEL1 |= (1u << 22) | (1u << 24);  /* P0.27 SDA0, P0.28 SCL0 */
  LPC_I2C0->I2SCLH = 125; LPC_I2C0->I2SCLL = 125;
  LPC_I2C0->I2CONSET = 0x40;
  box[0] = read_reg(0xD0);
  box[3] = 0xC0DE;
  while (1) {}
}
'''


def wire_bmp(c, pullups=True):
    c.add_part('bmp280', 'bmp')
    for a, b in [('bmp.VCC', 'mcu.3V3'), ('bmp.GND', 'mcu.GND'), ('bmp.SDA', 'mcu.P0.27'), ('bmp.SCL', 'mcu.P0.28')]:
        c.connect(a, b)
    if pullups:
        for n, line in ((1, 'SDA'), (2, 'SCL')):
            c.add_part('resistor', f'pu{n}', {'ohms': 4700})
            c.connect(f'pu{n}.1', f'bmp.{line}')
            c.connect(f'pu{n}.2', 'mcu.3V3')


def test_i2c_reads_bmp280_chip_id():
    m = machine(I2C_BMP)
    wire_bmp(m.board.circuit)
    assert run_until(m, lambda: mailbox(m)[3] == 0xC0DE, slices=3000)
    assert mailbox(m)[0] == 0x58


def test_i2c_without_pullups_never_starts():
    m = machine(I2C_BMP)
    wire_bmp(m.board.circuit, pullups=False)
    run_until(m, lambda: mailbox(m)[3] == 0xC0DE, slices=200)
    assert mailbox(m)[3] != 0xC0DE
    assert 'I2C0:pullups' in m.notes


def test_bmp280_compensation_round_trip():
    m = Machine(build('int main(void){while(1){}}'), target='bare')
    bmp = m.board.circuit.add_part('bmp280', 'bmp')
    bmp.set_stimulus('celsius', 31.25)
    bmp.set_stimulus('hpa', 950.0)
    bmp.measure()
    r = bmp.registers
    adc_t = (r[0xFA] << 12) | (r[0xFB] << 4) | (r[0xFC] >> 4)
    adc_p = (r[0xF7] << 12) | (r[0xF8] << 4) | (r[0xF9] >> 4)
    t_fine, t = bmp.compensate_t(adc_t)
    assert t == pytest.approx(3125, abs=1)
    assert bmp.compensate_p(adc_p, t_fine) / 256 == pytest.approx(95000, abs=2)


def test_keil_style_systick_priority_and_irq32_enable_are_accepted():
    m = machine(r'''
volatile unsigned ticks;
void SysTick_Handler(void) { ticks++; }
int main(void) {
  *(volatile unsigned char *)0xE000ED23 = 0xF8;     /* CMSIS core_cm3 SCB->SHP[11] */
  NVIC->ISER[1] = 1;                                  /* IRQ32 (PLL1) */
  SysTick_Config(1000);
  while (1) { *(volatile unsigned *)0x10007000 = ticks; }
}''')
    assert run_until(m, lambda: mailbox(m)[0] > 3, slices=400)
    assert m.enabled_irq >> 32 & 1
    assert m._priority(-1) == 0xF8


def test_higher_priority_interrupt_preempts_a_running_handler():
    m = machine(r'''
volatile unsigned *box = (volatile unsigned *)0x10007000;
void TIMER0_IRQHandler(void) {
  box[0] = 1; NVIC_SetPendingIRQ(TIMER1_IRQn);
  for (volatile int i = 0; i < 200; i++) {}
  box[2] = box[1]; LPC_TIM0->IR = 1; NVIC_DisableIRQ(TIMER0_IRQn);
}
void TIMER1_IRQHandler(void) { box[1] = 7; }
int main(void) {
  NVIC_SetPriority(TIMER0_IRQn, 4); NVIC_SetPriority(TIMER1_IRQn, 1);
  NVIC_EnableIRQ(TIMER1_IRQn); NVIC_EnableIRQ(TIMER0_IRQn);
  NVIC_SetPendingIRQ(TIMER0_IRQn);
  while (1) {}
}''')
    assert run_until(m, lambda: mailbox(m)[2] == 7, slices=200)


def test_pwm1_on_p2_0_drives_an_external_led_with_duty():
    m = machine(r'''int main(void) {
      LPC_PINCON->PINSEL4 = 1;           /* P2.0 PWM1.1 */
      LPC_PWM1->MR0 = 1000; LPC_PWM1->MR1 = 300; LPC_PWM1->MCR = 2;
      LPC_PWM1->PCR = 1u << 9; LPC_PWM1->LER = 3; LPC_PWM1->TCR = 9;
      while (1) {} }''')
    c = m.board.circuit
    c.add_part('resistor', 'r1', {'ohms': 680})
    led = c.add_part('led', 'led1')
    c.connect('mcu.P2.0', 'r1.1'); c.connect('r1.2', 'led1.A'); c.connect('led1.K', 'mcu.GND')
    m.run(20000)
    assert m.pwm_duty(1, (2, 0)) == pytest.approx(0.3)
    seen = set()
    for _ in range(200):
        m.run(500)
        seen.add(m.pin_output(2, 0))
    assert seen == {0, 1}


def test_adc_channel_0_reads_an_external_potentiometer():
    m = machine(r'''int main(void) {
      LPC_SC->PCONP |= 1u << 12; LPC_PINCON->PINSEL1 |= 1u << 14;  /* P0.23 AD0.0 */
      LPC_PINCON->PINMODE1 |= 2u << 14;                            /* no pull-up on the analog pin */
      LPC_ADC->ADCR = 1 | (4u << 8) | (1u << 21);
      while (1) { LPC_ADC->ADCR |= 1u << 24; while (!(LPC_ADC->ADGDR & (1u << 31))) {}
        *(volatile unsigned *)0x10007000 = (LPC_ADC->ADGDR >> 4) & 0xFFF; } }''')
    c = m.board.circuit
    c.add_part('potentiometer', 'pot')
    c.connect('pot.1', 'mcu.GND'); c.connect('pot.3', 'mcu.3V3'); c.connect('pot.W', 'mcu.P0.23')
    c.set_stimulus('pot', 'position', 0.5)
    m.run(200000)
    assert mailbox(m)[0] == pytest.approx(2048, abs=20)


def test_default_pull_up_skews_a_high_impedance_adc_reading():
    # Same divider, PINMODE left at reset (pull-up): ~50 uA into a 2.5 kOhm source.
    m = machine(r'''int main(void) {
      LPC_SC->PCONP |= 1u << 12; LPC_PINCON->PINSEL1 |= 1u << 14;
      LPC_ADC->ADCR = 1 | (4u << 8) | (1u << 21);
      while (1) { LPC_ADC->ADCR |= 1u << 24; while (!(LPC_ADC->ADGDR & (1u << 31))) {}
        *(volatile unsigned *)0x10007000 = (LPC_ADC->ADGDR >> 4) & 0xFFF; } }''')
    c = m.board.circuit
    c.add_part('potentiometer', 'pot')
    c.connect('pot.1', 'mcu.GND'); c.connect('pot.3', 'mcu.3V3'); c.connect('pot.W', 'mcu.P0.23')
    m.run(200000)
    assert 2100 < mailbox(m)[0] < 2150


def test_external_button_raises_eint0_and_gpio_interrupt():
    m = machine(r'''
volatile unsigned *box = (volatile unsigned *)0x10007000;
void EINT0_IRQHandler(void) { LPC_SC->EXTINT = 1; box[0]++; }
void EINT3_IRQHandler(void) { if (LPC_GPIOINT->IO0IntStatF & (1u << 4)) box[1]++; LPC_GPIOINT->IO0IntClr = 1u << 4; }
int main(void) {
  LPC_PINCON->PINSEL4 |= 1u << 20; LPC_SC->EXTMODE = 1; LPC_SC->EXTPOLAR = 0;  /* P2.10 falling edge */
  LPC_GPIOINT->IO0IntEnF = 1u << 4;
  NVIC_EnableIRQ(EINT0_IRQn); NVIC_EnableIRQ(EINT3_IRQn);
  while (1) {} }''')
    c = m.board.circuit
    c.add_part('button', 'b1')
    c.add_part('button', 'b2')
    c.connect('b1.1', 'mcu.P2.10'); c.connect('b1.4', 'mcu.GND')
    c.connect('b2.1', 'mcu.P0.4'); c.connect('b2.4', 'mcu.GND')
    m.run(20000)
    for part in ('b1', 'b2'):
        c.set_stimulus(part, 'pressed', 1); m.run(20000)
        c.set_stimulus(part, 'pressed', 0); m.run(20000)
    assert mailbox(m)[:2] == (1, 1)


def test_timer_capture_measures_a_generated_pulse():
    m = machine(r'''
volatile unsigned *box = (volatile unsigned *)0x10007000;
void TIMER2_IRQHandler(void) { box[box[3]++ & 1] = LPC_TIM2->CR0; LPC_TIM2->IR = 1u << 4; }
int main(void) {
  LPC_SC->PCONP |= 1u << 22; LPC_PINCON->PINSEL0 |= 3u << 8;   /* P0.4 CAP2.0 */
  LPC_SC->PCLKSEL1 |= 1u << 12;                               /* PCLK = CCLK */
  LPC_TIM2->PR = 99; LPC_TIM2->CCR = 7; LPC_TIM2->TCR = 1;     /* 1 us ticks, both edges, IRQ */
  NVIC_EnableIRQ(TIMER2_IRQn);
  while (1) {} }''')
    c = m.board.circuit
    c.add_part('signal_generator', 'gen')
    c.connect('gen.OUT', 'mcu.P0.4'); c.connect('gen.GND', 'mcu.GND')
    c.set_stimulus('gen', 'duty', 0.25)
    c.set_stimulus('gen', 'hz', 1000.0)
    assert run_until(m, lambda: mailbox(m)[3] >= 6, slices=4000)
    a, b = mailbox(m)[:2]
    assert abs(abs(int(b) - int(a)) % 1000 - 250) <= 3 or abs(abs(int(b) - int(a)) % 1000 - 750) <= 3


def test_dac_output_is_a_measurable_voltage():
    m = machine(r'''int main(void) { LPC_PINCON->PINSEL1 |= 2u << 20; LPC_DAC->DACR = 512u << 6; while (1) {} }''')
    c = m.board.circuit
    c.add_part('resistor', 'load', {'ohms': 100_000})
    c.connect('mcu.P0.26', 'load.1'); c.connect('load.2', 'mcu.GND')
    m.run(5000)
    assert m.board.pad_voltage(0, 26) == pytest.approx(1.65, abs=0.01)


def test_rit_interrupt_and_bitband_gpio():
    m = machine(r'''
volatile unsigned count;
void RIT_IRQHandler(void) { LPC_RIT->RICTRL |= 1; count++;
  *(volatile unsigned *)(0x22000000 + ((0x2009C018 - 0x20000000) * 32) + 4 * 4) = 1; }
int main(void) {
  LPC_GPIO0->FIODIR = 1u << 4;
  LPC_SC->PCONP |= 1u << 16; LPC_RIT->RICOMPVAL = 2000; LPC_RIT->RICTRL = 0x0A;
  NVIC_EnableIRQ(RIT_IRQn);
  while (1) { *(volatile unsigned *)0x10007000 = count; } }''')
    assert run_until(m, lambda: mailbox(m)[0] >= 2, slices=400)
    assert m.gpio[0].latch & (1 << 4)


def test_pll_without_feed_and_overclock_are_explained():
    m = Machine(build('int main(void){while(1){}}'), target='bare')
    m.write_word(m.SC + 0x10C, 1)
    m.write_word(m.SC + 0x84, 0x00050063)
    m.write_word(m.SC + 0x80, 3)
    assert 'clock:feed' in m.notes and 'clock:cclk' in m.notes
    assert 'FEED' in m.notes['clock:feed'] or 'feed' in m.notes['clock:feed']
