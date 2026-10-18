/*
 * taskstack - print a waiting task's state and the words on its saved stack.
 *
 *   taskstack NAME [LO HI]
 *
 * NAME is the task's node name (a Shell command's process is named after the
 * command, e.g. "RAM:pc/PhotoCraft"). With LO and HI (hex), only words in
 * [LO, HI) are printed: the candidate return addresses into one program, which
 * the host turns into function names with nm (see the evidence report).
 * Diagnostics for a process that does not end; it only reads exec structures
 * inside Forbid() and changes nothing.
 */
#include <proto/exec.h>
#include <exec/execbase.h>
#include <exec/tasks.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    static IPTR words[4096];
    struct Task *t;
    IPTR lo = 0, hi = ~(IPTR)0, *sp, *top;
    ULONG sigwait, sigrecvd;
    int n = 0, i;

    if (argc < 2) {
        printf("usage: taskstack NAME [LO HI]\n");
        return 20;
    }
    if (argc >= 4) {
        lo = (IPTR)strtoull(argv[2], NULL, 16);
        hi = (IPTR)strtoull(argv[3], NULL, 16);
    }
    Forbid();
    t = FindTask((CONST_STRPTR)argv[1]);
    if (!t) {
        Permit();
        printf("no task named %s\n", argv[1]);
        return 10;
    }
    sigwait = t->tc_SigWait;
    sigrecvd = t->tc_SigRecvd;
    sp = (IPTR *)t->tc_SPReg;
    top = (IPTR *)t->tc_SPUpper;
    for (; sp && sp < top && n < 4096; sp++)
        if (*sp >= lo && *sp < hi)
            words[n++] = *sp;
    Permit();
    printf("task %s state %d sigwait %08lx sigrecvd %08lx sp %p upper %p\n", argv[1], (int)t->tc_State,
           (unsigned long)sigwait, (unsigned long)sigrecvd, (void *)t->tc_SPReg, (void *)t->tc_SPUpper);
    for (i = 0; i < n; i++)
        printf("%lx\n", (unsigned long)words[i]);
    return 0;
}
