/* hello: the first program. Prints a greeting and a little arithmetic. */
#include "rv.h"

static u32 fib(u32 n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }

int main(void)
{
    puts_("hello from RISC-V on DiamondFire\n");
    puts_("fib(15) = ");
    putu(fib(15));
    puts_("\n");
    return 0;
}
