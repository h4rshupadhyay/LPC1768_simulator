#include <LPC17xx.h>

const unsigned char seven_seg[16] = {
    0x3F,0x06,0x5B,0x4F,0x66,0x6D,0x7D,0x07,
    0x7F,0x6F,0x77,0x7C,0x39,0x5E,0x79,0x71
};

#define SEG_SHIFT       4
#define DIGIT_ENABLE_P1 (1<<23)
#define DIGIT_ENABLE_MASK (0x0F<<23)
#define COL_BASE_BIT    15
#define ROW_BASE_BIT    19
#define COL_MASK ((0x0F) << COL_BASE_BIT)
#define ROW_MASK ((0x0F) << ROW_BASE_BIT)

static void short_delay(volatile unsigned int d){ while(d--) __NOP(); }

int main(void){
    unsigned int col_idx,row_idx;
    unsigned int candidate = 0xFF;
    unsigned int stable = 0;
    unsigned int displayed = 0xFF;
		unsigned int row_bits;
    LPC_PINCON->PINSEL0 &= ~(0xFFFFFFFF);
    LPC_PINCON->PINSEL1 &= ~(0xFFFFFFFF);
    LPC_GPIO0->FIODIR |= (0xFF << SEG_SHIFT);
    LPC_GPIO0->FIODIR |= COL_MASK;
    LPC_GPIO0->FIODIR &= ~ROW_MASK;
    LPC_GPIO1->FIODIR |= DIGIT_ENABLE_MASK;
    LPC_GPIO0->FIOPIN &= ~(0xFF << SEG_SHIFT);
    LPC_GPIO1->FIOPIN &= ~DIGIT_ENABLE_MASK;
    LPC_GPIO0->FIOSET = COL_MASK;

    for(;;){
        unsigned int read_key = 0xFF;
        for(col_idx=0; col_idx<4; col_idx++){
            LPC_GPIO0->FIOSET = COL_MASK;
            short_delay(50);
            LPC_GPIO0->FIOCLR = (1 << (COL_BASE_BIT + col_idx));
            short_delay(200);
            row_bits = (LPC_GPIO0->FIOPIN & ROW_MASK) >> ROW_BASE_BIT;
            if(row_bits != 0x0F){
                for(row_idx=0; row_idx<4; row_idx++){
                    if((row_bits & (1<<row_idx)) == 0){
                        read_key = col_idx*4 + row_idx;
                        break;
                    }
                }
                LPC_GPIO0->FIOSET = COL_MASK;
                break;
            }
            LPC_GPIO0->FIOSET = COL_MASK;
        }

        if(read_key == candidate){
            if(stable < 3) stable++;
        } else {
            candidate = read_key;
            stable = 1;
        }

        if(stable >= 3){
            if(candidate != 0xFF){
                displayed = candidate & 0x0F;
            }
            stable = 3;
        }

        if(displayed != 0xFF){
            unsigned int seg = seven_seg[displayed];
            LPC_GPIO0->FIOCLR = (0xFF << SEG_SHIFT);
            LPC_GPIO0->FIOSET = (seg << SEG_SHIFT);
            LPC_GPIO1->FIOCLR = DIGIT_ENABLE_MASK;
            LPC_GPIO1->FIOSET = DIGIT_ENABLE_P1;
        }

        short_delay(3000);
    }
}
