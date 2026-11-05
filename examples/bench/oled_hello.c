/* SSD1306 128x64 OLED over I2C2 on the ALS kit (SDA = CNA.7, SCL = CNA.8).
 * Initializes the panel (including the charge pump) and draws a frame,
 * a checkerboard and a bar that grows over time.
 */
#include <LPC17xx.h>

#define OLED 0x3C

static void i2c_wait(void) { while (!(LPC_I2C2->I2CONSET & 0x08)) {} }
static void i2c_begin(void)
{
    LPC_I2C2->I2CONSET = 0x20; LPC_I2C2->I2CONCLR = 0x08; i2c_wait(); LPC_I2C2->I2CONCLR = 0x20;
    LPC_I2C2->I2DAT = OLED << 1; LPC_I2C2->I2CONCLR = 0x08; i2c_wait();
}
static void i2c_byte(unsigned char b) { LPC_I2C2->I2DAT = b; LPC_I2C2->I2CONCLR = 0x08; i2c_wait(); }
static void i2c_end(void) { LPC_I2C2->I2CONSET = 0x10; LPC_I2C2->I2CONCLR = 0x08; }

static void command(unsigned char c) { i2c_begin(); i2c_byte(0x00); i2c_byte(c); i2c_end(); }

static unsigned char frame[8][128];

static void flush(void)
{
    command(0x21); command(0); command(127);       /* column range */
    command(0x22); command(0); command(7);         /* page range */
    i2c_begin(); i2c_byte(0x40);
    for (int page = 0; page < 8; page++)
        for (int col = 0; col < 128; col++) i2c_byte(frame[page][col]);
    i2c_end();
}

static void pixel(int x, int y) { frame[y >> 3][x] |= 1u << (y & 7); }

int main(void)
{
    SystemInit();
    LPC_SC->PCONP |= 1u << 26;
    LPC_PINCON->PINSEL0 |= (2u << 20) | (2u << 22);
    LPC_PINCON->PINMODE_OD0 |= (1u << 10) | (1u << 11);
    LPC_I2C2->I2SCLH = 32; LPC_I2C2->I2SCLL = 31;     /* ~400 kHz */
    LPC_I2C2->I2CONSET = 0x40;

    static const unsigned char init[] = {0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40, 0x8D, 0x14,
                                         0x20, 0x00, 0xA1, 0xC8, 0xDA, 0x12, 0x81, 0xCF, 0xD9, 0xF1,
                                         0xDB, 0x40, 0xA4, 0xA6, 0xAF};
    for (unsigned i = 0; i < sizeof init; i++) command(init[i]);

    for (int x = 0; x < 128; x++) { pixel(x, 0); pixel(x, 63); }
    for (int y = 0; y < 64; y++) { pixel(0, y); pixel(127, y); }
    for (int y = 8; y < 32; y++)
        for (int x = 8; x < 56; x++)
            if (((x >> 3) + (y >> 3)) & 1) pixel(x, y);
    int bar = 0;
    while (1) {
        for (int y = 44; y < 54; y++) pixel(8 + bar, y);
        if (++bar > 110) {
            bar = 0;
            for (int page = 5; page < 7; page++)
                for (int col = 8; col < 120; col++) frame[page][col] = 0;
        }
        flush();
    }
}
