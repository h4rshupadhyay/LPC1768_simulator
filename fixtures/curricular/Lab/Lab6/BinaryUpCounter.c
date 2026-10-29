#include <LPC17xx.h>

int main(){
	int i;
	unsigned long x, j;
	LPC_PINCON->PINSEL0 = 0;   

	LPC_GPIO0->FIODIR = 0xFF<<15; 
	
	x = 1<<15; // new variable
	
	while(1){
	x = 1<<15; 
				for(i=0;i<256;i++){
					LPC_GPIO0->FIOSET=x;
					for(j=0; j<2000000; j++);
					
					x = x + (1<<15);
					
					LPC_GPIO0->FIOCLR=-x;
					for(j=0; j<2000000; j++);
				}
	}
}
