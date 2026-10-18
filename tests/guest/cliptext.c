/* cliptext: put its argument's bytes on clipboard unit 0 as IFF FTXT text, as a
 * system program would (ISO 8859-1 on AROS). Used to test pasting into
 * PhotoCraft without driving another program's copy command.
 *
 *     cliptext "text"     exit 0 when the clip was written, 10 otherwise
 */
#include <proto/exec.h>
#include <proto/iffparse.h>
#include <libraries/iffparse.h>
#include <string.h>
#include <stdio.h>

#define ID_FTXT MAKE_ID('F', 'T', 'X', 'T')
#define ID_CHRS MAKE_ID('C', 'H', 'R', 'S')

struct Library *IFFParseBase;

int main(int argc, char **argv)
{
    struct IFFHandle *iff;
    int rc = 10;

    if (argc != 2) {
        printf("usage: cliptext TEXT\n");
        return 10;
    }
    IFFParseBase = OpenLibrary("iffparse.library", 39);
    if (!IFFParseBase)
        return 10;
    if ((iff = AllocIFF())) {
        if ((iff->iff_Stream = (IPTR)OpenClipboard(0))) {
            InitIFFasClip(iff);
            if (!OpenIFF(iff, IFFF_WRITE)) {
                LONG len = strlen(argv[1]);
                if (!PushChunk(iff, ID_FTXT, ID_FORM, IFFSIZE_UNKNOWN)
                    && !PushChunk(iff, 0, ID_CHRS, len)
                    && WriteChunkBytes(iff, argv[1], len) == len
                    && !PopChunk(iff) && !PopChunk(iff))
                    rc = 0;
                CloseIFF(iff);
            }
            CloseClipboard((struct ClipboardHandle *)iff->iff_Stream);
        }
        FreeIFF(iff);
    }
    CloseLibrary(IFFParseBase);
    printf("cliptext: %s (%d bytes)\n", rc ? "failed" : "written", (int)strlen(argv[1]));
    return rc;
}
