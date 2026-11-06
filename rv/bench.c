/* bench: a CPU benchmark. Counts the primes below 3000 with a sieve,
 * then reports the instructions it took (the runner times them). */
#include "rv.h"

static u8 composite[3000];

int main(void)
{
    u32 start = sys_instret();
    int primes = 0;
    for (int i = 2; i < 3000; i++) {
        if (!composite[i]) {
            primes++;
            for (int j = i * i; j < 3000; j += i) composite[j] = 1;
        }
    }
    u32 used = sys_instret() - start;
    puts_("primes below 3000: ");
    puti(primes);
    puts_("\n");
    puts_("instructions: ");
    putu(used);
    puts_("\n");
    return 0;
}
