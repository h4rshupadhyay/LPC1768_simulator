/* BMP280 over I2C2 on the ALS kit: SDA = CNA.7 (P0.10), SCL = CNA.8 (P0.11),
 * 4.7 kOhm pull-ups to the kit's 3V3 tap. Prints chip ID, temperature and pressure on UART0.
 */
#include <LPC17xx.h>
#include <stdint.h>

#define ADDR 0x76

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
static void putd(int32_t v, int decimals)
{
    char buffer[16];
    int i = 15, digits = 0;
    unsigned u = v < 0 ? -v : v;
    buffer[i] = 0;
    do {
        if (decimals && digits == decimals) buffer[--i] = '.';
        buffer[--i] = '0' + u % 10; u /= 10; digits++;
    } while (u || digits <= decimals);
    if (v < 0) buffer[--i] = '-';
    puts0(&buffer[i]);
}

/* -- I2C2 master, polled (UM10360 chapter 19 state codes) -- */
static void i2c_wait(void) { while (!(LPC_I2C2->I2CONSET & 0x08)) {} }
static int i2c_start(unsigned char address_rw)
{
    LPC_I2C2->I2CONSET = 0x20;                 /* STA */
    LPC_I2C2->I2CONCLR = 0x08;
    i2c_wait();
    LPC_I2C2->I2CONCLR = 0x20;
    LPC_I2C2->I2DAT = address_rw;
    LPC_I2C2->I2CONCLR = 0x08;
    i2c_wait();
    return LPC_I2C2->I2STAT == 0x18 || LPC_I2C2->I2STAT == 0x40;
}
static void i2c_stop(void) { LPC_I2C2->I2CONSET = 0x10; LPC_I2C2->I2CONCLR = 0x08; }
static void i2c_write(unsigned char byte) { LPC_I2C2->I2DAT = byte; LPC_I2C2->I2CONCLR = 0x08; i2c_wait(); }
static unsigned char i2c_read(int ack)
{
    if (ack) LPC_I2C2->I2CONSET = 0x04; else LPC_I2C2->I2CONCLR = 0x04;
    LPC_I2C2->I2CONCLR = 0x08;
    i2c_wait();
    return LPC_I2C2->I2DAT;
}
static int read_regs(unsigned char reg, unsigned char *out, int count)
{
    if (!i2c_start(ADDR << 1)) { i2c_stop(); return 0; }
    i2c_write(reg);
    if (!i2c_start((ADDR << 1) | 1)) { i2c_stop(); return 0; }
    for (int i = 0; i < count; i++) out[i] = i2c_read(i < count - 1);
    i2c_stop();
    return 1;
}
static void write_reg(unsigned char reg, unsigned char value)
{
    if (i2c_start(ADDR << 1)) { i2c_write(reg); i2c_write(value); }
    i2c_stop();
}

static void delay_ms(unsigned ms)
{
    LPC_TIM0->TCR = 2; LPC_TIM0->PR = SystemCoreClock / 4 / 1000 - 1; LPC_TIM0->TCR = 1;
    while (LPC_TIM0->TC < ms) {}
}

int main(void)
{
    SystemInit();
    uart0_init();
    LPC_SC->PCONP |= 1u << 26;                                    /* I2C2 power */
    LPC_PINCON->PINSEL0 |= (2u << 20) | (2u << 22);               /* P0.10 SDA2, P0.11 SCL2 */
    LPC_PINCON->PINMODE_OD0 |= (1u << 10) | (1u << 11);           /* open drain on the I2C lines */
    LPC_I2C2->I2SCLH = 125; LPC_I2C2->I2SCLL = 125;               /* 25 MHz / 250 = 100 kHz */
    LPC_I2C2->I2CONSET = 0x40;                                    /* I2EN */

    unsigned char id = 0, cal[24], raw[6];
    if (!read_regs(0xD0, &id, 1)) { puts0("BMP280 did not answer (wiring, power or pull-ups?)\r\n"); while (1) {} }
    puts0("chip id 0x"); putc0("0123456789ABCDEF"[id >> 4]); putc0("0123456789ABCDEF"[id & 15]); puts0("\r\n");
    read_regs(0x88, cal, 24);
    uint16_t T1 = cal[0] | cal[1] << 8; int16_t T2 = cal[2] | cal[3] << 8, T3 = cal[4] | cal[5] << 8;
    uint16_t P1 = cal[6] | cal[7] << 8;
    int16_t P2 = cal[8] | cal[9] << 8, P3 = cal[10] | cal[11] << 8, P4 = cal[12] | cal[13] << 8,
            P5 = cal[14] | cal[15] << 8, P6 = cal[16] | cal[17] << 8, P7 = cal[18] | cal[19] << 8,
            P8 = cal[20] | cal[21] << 8, P9 = cal[22] | cal[23] << 8;
    write_reg(0xF4, 0x27);                                        /* normal mode, x1 oversampling */
    while (1) {
        if (!read_regs(0xF7, raw, 6)) { puts0("BMP280 stopped answering\r\n"); delay_ms(500); continue; }
        int32_t adc_p = (raw[0] << 12) | (raw[1] << 4) | (raw[2] >> 4);
        int32_t adc_t = (raw[3] << 12) | (raw[4] << 4) | (raw[5] >> 4);
        int32_t var1 = ((((adc_t >> 3) - ((int32_t)T1 << 1))) * T2) >> 11;
        int32_t var2 = (((((adc_t >> 4) - T1) * ((adc_t >> 4) - T1)) >> 12) * T3) >> 14;
        int32_t t_fine = var1 + var2, celsius100 = (t_fine * 5 + 128) >> 8;
        int64_t v1 = (int64_t)t_fine - 128000, v2 = v1 * v1 * P6;
        v2 += (v1 * P5) << 17; v2 += (int64_t)P4 << 35;
        v1 = ((v1 * v1 * P3) >> 8) + ((v1 * P2) << 12);
        v1 = ((((int64_t)1) << 47) + v1) * P1 >> 33;
        int64_t p = 1048576 - adc_p;
        p = (((p << 31) - v2) * 3125) / v1;
        v1 = ((int64_t)P9 * (p >> 13) * (p >> 13)) >> 25;
        v2 = ((int64_t)P8 * p) >> 19;
        p = ((p + v1 + v2) >> 8) + ((int64_t)P7 << 4);
        puts0("T = "); putd(celsius100, 2); puts0(" C   P = "); putd((int32_t)(p / 256), 0); puts0(" Pa\r\n");
        delay_ms(1000);
    }
}
