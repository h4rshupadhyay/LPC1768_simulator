/* UART0 hello + echo. Open the Serial tab (UART0, 9600 baud) and type. */
#include <LPC17xx.h>

static void uart0_init(unsigned baud)
{
    LPC_PINCON->PINSEL0 = (LPC_PINCON->PINSEL0 & ~0xF0u) | 0x50u;  /* P0.2 TXD0, P0.3 RXD0 */
    LPC_UART0->LCR = 0x83;                                       /* 8N1, DLAB = 1 */
    unsigned divisor = SystemCoreClock / 4 / (16 * baud);        /* PCLK = CCLK / 4 */
    LPC_UART0->DLL = divisor & 0xFF;
    LPC_UART0->DLM = divisor >> 8;
    LPC_UART0->LCR = 0x03;                                       /* DLAB = 0 */
    LPC_UART0->FCR = 0x07;                                       /* enable and reset FIFOs */
}

static void uart0_putc(char c)
{
    while (!(LPC_UART0->LSR & 0x20)) {}                          /* wait for THRE */
    LPC_UART0->THR = c;
}

static void uart0_puts(const char *s)
{
    while (*s) {
        if (*s == '\n') uart0_putc('\r');
        uart0_putc(*s++);
    }
}

int main(void)
{
    SystemInit();
    uart0_init(9600);
    uart0_puts("Hello from the LPC1768!\nType something:\n");
    while (1) {
        if (LPC_UART0->LSR & 1) {                                /* RDR: a byte arrived */
            char c = LPC_UART0->RBR;
            uart0_putc(c);
            if (c == '\r') uart0_putc('\n');
        }
    }
}
