/* HC-SR04 distance on the mbed module.
 * TRIG = p5 (P0.9), ECHO = p8 (P0.6) through a 10k/18k divider (5 V -> 3.2 V).
 * Timer0 counts microseconds; the distance prints on UART0 (Serial tab, 9600 baud).
 */
#include <LPC17xx.h>

#define TRIG (1u << 9)
#define ECHO (1u << 6)

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
    char buffer[11];
    int i = 10;
    buffer[i] = 0;
    do { buffer[--i] = '0' + v % 10; v /= 10; } while (v);
    puts0(&buffer[i]);
}

static unsigned now_us(void) { return LPC_TIM0->TC; }
static void wait_us(unsigned us) { unsigned start = now_us(); while (now_us() - start < us) {} }

int main(void)
{
    SystemInit();
    uart0_init();
    LPC_TIM0->PR = SystemCoreClock / 4 / 1000000 - 1;   /* 1 MHz timer tick */
    LPC_TIM0->TCR = 2;
    LPC_TIM0->TCR = 1;
    LPC_GPIO0->FIODIR |= TRIG;
    LPC_GPIO0->FIODIR &= ~ECHO;
    puts0("HC-SR04 ready\r\n");
    while (1) {
        LPC_GPIO0->FIOSET = TRIG;
        wait_us(12);
        LPC_GPIO0->FIOCLR = TRIG;

        unsigned start = now_us();
        while (!(LPC_GPIO0->FIOPIN & ECHO)) {
            if (now_us() - start > 30000) break;           /* no echo started */
        }
        unsigned rise = now_us();
        while (LPC_GPIO0->FIOPIN & ECHO) {
            if (now_us() - rise > 40000) break;            /* out of range */
        }
        unsigned width = now_us() - rise;
        puts0("distance: ");
        putu(width / 58);
        puts0(" cm\r\n");
        wait_us(200000);
    }
}
