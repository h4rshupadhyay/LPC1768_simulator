#include "LPC17xx.h"

// Global variables for PWM control
unsigned long int duty_cycle = 0;  // Current duty cycle value (0-3000)
int direction = 1;                  // Direction of duty cycle change: 1=increasing, 0=decreasing
int step = 50;                      // Amount to change duty cycle per interrupt

// PWM1 Interrupt Service Routine
// Called when PWM match register 0 triggers an interrupt
void PWM1_IRQHandler(void)
{
    // Check if interrupt flag for PWM match channel 0 is set
    if (LPC_PWM1->IR & (1 << 0))
    {
        // Ramp up the duty cycle if direction is 1
        if (direction == 1)
        {
            duty_cycle += step;
            // Check if we've reached maximum duty cycle
            if (duty_cycle >= 3000)
            {
                duty_cycle = 3000;
                direction = 0;  // Change direction to decreasing
            }
        }
        // Ramp down the duty cycle if direction is 0
        else
        {
            duty_cycle -= step;
            // Check if we've reached minimum duty cycle
            if (duty_cycle <= 0)
            {
                duty_cycle = 0;
                direction = 1;  // Change direction to increasing
            }
        }

        // Update PWM match register 4 with new duty cycle
        LPC_PWM1->MR4 = duty_cycle;
        // Latch the new match value
        LPC_PWM1->LER = (1 << 4);
        // Clear the interrupt flag for channel 0
        LPC_PWM1->IR = (1 << 0);
    }
}

int main(void)
{
    // Configure P2.5 as PWM1[4] output
    // PINSEL3 bits 15:14 = 10 for PWM1[4] function
    LPC_PINCON->PINSEL3 |= (2 << 14);

    // Reset and configure PWM1 counter and prescaler
    LPC_PWM1->TCR = (1 << 1);     // Reset PWM counter
    LPC_PWM1->CTCR = 0;           // Timer mode (counter increments on PCLK)
    LPC_PWM1->PR = 0;             // Prescaler = 0 (no prescaling)

    // Set PWM cycle period and initial duty cycle
    LPC_PWM1->MR0 = 3000;         // PWM period (match register 0)
    LPC_PWM1->MR4 = duty_cycle;   // Initial duty cycle (match register 4)

    // Configure PWM interrupts and enable output
    LPC_PWM1->MCR = (1 << 1) | (1 << 0);  // Reset on MR0 and interrupt on MR0
    LPC_PWM1->PCR = (1 << 12);            // Enable PWM4 output

    // Latch the match register values
    LPC_PWM1->LER = (1 << 0) | (1 << 4);

    // Enable PWM1 interrupt in NVIC
    NVIC_EnableIRQ(PWM1_IRQn);

    // Start PWM counter and enable PWM mode
    LPC_PWM1->TCR = (1 << 0) | (1 << 3);  // Counter enable and PWM enable

    // Infinite loop - everything is handled by interrupts
    while (1);
}
