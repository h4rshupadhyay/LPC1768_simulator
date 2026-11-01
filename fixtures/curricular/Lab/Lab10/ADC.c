#include <LPC17xx.h>

unsigned long result, y; // global variable for ADC result

int main(){
	LPC_PINCON -> PINSEL3 = 3 << 28; // P1.30 function 3
	LPC_SC -> PCONP = 1 << 12; // power control
	
	// ADCR
	LPC_ADC -> ADCR = 1 << 4 | 1 << 16 | 1 << 21 ;  // ADC4, burst mode, ADC enable, start now
	// 1 << 24 instead of 1<<16 for non burst
	LPC_ADC -> ADINTEN = (1 << 4); // Interrupt (4th channel to be enabled)
	
	NVIC_EnableIRQ(ADC_IRQn); // Nested Vector Interrupt Controller
	
	while(1){} // infinite delay
}

void ADC_IRQHandler(void)
{
    result = (LPC_ADC -> ADGDR & (0xFFF << 4) >> 4 );  // Read 12-bit ADC result
	  y  = (LPC_ADC -> ADDR4 & (0xFFF << 4) >> 4); // Done bit reset
}
