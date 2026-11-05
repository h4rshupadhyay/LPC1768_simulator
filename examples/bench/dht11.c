/* DHT11 humidity/temperature on the mbed module, DATA = p5 (P0.9) with the
 * module's pull-up. Timer0 times the 26-28 us / 70 us HIGH pulses.
 * Select "Precise (us)" timing on the Workbench for microsecond-accurate replies.
 */
#include <LPC17xx.h>

#define DATA (1u << 9)

static void uart0_init(void)
{
    LPC_PINCON->PINSEL0 = (LPC_PINCON->PINSEL0 & ~0xF0u) | 0x50u;
    LPC_UART0->LCR = 0x83;
    unsigned divisor = SystemCoreClock / 4 / (16 * 9600);
    LPC_UART0->DLL = divisor & 0xFF;
    LPC_UART0->DLM = divisor >> 8;
    LPC_UART0->LCR = 0x03;
}
static void putc0(char c) { while (!(LPC_UART0->LSR & 0x20)) {} LPC_UART0->THR = c; }
static void puts0(const char *s) { while (*s) putc0(*s++); }
static void putu(unsigned v)
{
    char buffer[11]; int i = 10; buffer[i] = 0;
    do { buffer[--i] = '0' + v % 10; v /= 10; } while (v);
    puts0(&buffer[i]);
}

static unsigned us(void) { return LPC_TIM0->TC; }
static void wait_us(unsigned t) { unsigned s = us(); while (us() - s < t) {} }
static int level(void) { return (LPC_GPIO0->FIOPIN & DATA) != 0; }
static int wait_level(int value, unsigned timeout)
{
    unsigned s = us();
    while (level() != value) if (us() - s > timeout) return -1;
    return us() - s;
}

static int read_dht(unsigned char out[5])
{
    LPC_GPIO0->FIOCLR = DATA;
    LPC_GPIO0->FIODIR |= DATA;          /* start signal: 18 ms LOW */
    wait_us(18000);
    LPC_GPIO0->FIODIR &= ~DATA;         /* release; the pull-up raises the line */
    if (wait_level(0, 200) < 0) return 0;     /* sensor answers LOW 80 us ... */
    if (wait_level(1, 200) < 0) return 0;     /* ... then HIGH 80 us */
    if (wait_level(0, 200) < 0) return 0;
    for (int i = 0; i < 40; i++) {
        if (wait_level(1, 200) < 0) return 0;  /* 50 us LOW separator */
        int high = wait_level(0, 200);
        if (high < 0) return 0;
        out[i / 8] = (out[i / 8] << 1) | (high > 45);
    }
    return ((out[0] + out[1] + out[2] + out[3]) & 0xFF) == out[4] ? 1 : -1;
}

int main(void)
{
    SystemInit();
    uart0_init();
    LPC_TIM0->PR = SystemCoreClock / 4 / 1000000 - 1;
    LPC_TIM0->TCR = 2;
    LPC_TIM0->TCR = 1;
    LPC_PINCON->PINMODE0 = (LPC_PINCON->PINMODE0 & ~(3u << 18)) | (2u << 18);  /* no internal pull */
    while (1) {
        unsigned char data[5] = {0};
        int ok = read_dht(data);
        if (ok == 1) {
            puts0("humidity "); putu(data[0]); puts0(" %  temperature "); putu(data[2]); puts0(" C\r\n");
        } else {
            puts0(ok ? "checksum error\r\n" : "no response\r\n");
        }
        wait_us(1200000);
    }
}
