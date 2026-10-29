#include <LPC17xx.h>

int main(){
	unsigned long x, y, i, j;

	LPC_PINCON->PINSEL0 = 0;
	LPC_GPIO0->FIODIR = 0xFF<<15;
	LPC_GPIO2->FIODIR = 0x0<<12;

	while(1){
		x = LPC_GPIO2->FIOPIN & (1 << 12);
		y = x ? (1<<22) : (1<<15);
		int dir = x ? 1 : 0;

		for(int k=0; k<2; k++){
			for(i=0; i<8; i++){
				LPC_GPIO0->FIOSET = y;
				y = dir ? y>>1 : y<<1;
				for(j=0; j<800000; j++);
			}
			y = x ? (1<<22) : (1<<15);
			LPC_GPIO0->FIOCLR = y;
		}
		for(i=0; i<8; i++){
			LPC_GPIO0->FIOCLR = y;
			y = dir ? y>>1 : y<<1;
			for(j=0; j<800000; j++);
		}
	}
}
