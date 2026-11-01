#include <LPC17xx.h>

int main(){
	unsigned long x, y, i, j;
	
	// LEDs
	LPC_PINCON->PINSEL0 = 0; 
	LPC_GPIO0->FIODIR = 0xFF<<15 | 0x0<<10; 
	
	
	
	while(1){
		x = LPC_GPIO0->FIOPIN & (1 << 10); 
		if(x){
				y = 1<<22;
				for(i=0;i<8;i++){
					LPC_GPIO0->FIOSET=y; 
					y = y>>1;
					for(j=0; j<800000; j++);
				}
				y = 1<<22;
				for(i=0;i<8;i++){
					LPC_GPIO0->FIOCLR=y;
					y>>=1;
					for(j=0; j<800000; j++);
				}
		}
		
		if(!x){
				y = 1<<15;
				for(i=0;i<8;i++){
					LPC_GPIO0->FIOSET=y; 
					y = y<<1;
					for(j=0; j<800000; j++);
				}
				y = 1<<15;
				for(i=0;i<8;i++){
					LPC_GPIO0->FIOCLR=y;
					y = y<<1;
					for(j=0; j<800000; j++);
				}
		}
	}
}

