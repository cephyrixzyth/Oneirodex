"""Shared, portable kaiju artwork for every server launcher.

Onei's fixed-width portrait uses a grayscale character ramp for a shaded,
image-to-ASCII look while staying plain 7-bit text with no runtime dependency.
The framed masthead and status plates borrow the composition of BBS logon
screens; Onei, the dream-waking kaiju, is original to Oneirodex.
"""

from __future__ import annotations

import sys


MASTHEAD = r"""
+============================================================================+
| ONEIRODEX // ABYSSAL WATCH                                FIELD TERMINAL  |
+============================================================================+
""".strip("\n")

TITAN = r"""
                                      ..,,,,...
                                    .,,,,,,,,,,.
                                   ,,,,:::::,,,,
                                 Xs.,,2:...,,2:.rA.
       ..                   ;r i##9H:s#2issiX#2,M9S9r ii
                          . 5G.SBGGB9GGS9##9#GG9&GG99.hM          .
                        ;  ,GGS&##S9BHGGHhhMGGH9BS#S&SG#r  ;.
                       ;Gi3SGSSS&BBBMh35522553hMBBB&SGSGShiHs
                       3S#SMMMhhH992AAAA25222AA2299HhhMMMS9SH
                      2#GGh33hhhAG93hhhhhMMhhhhh39GA3hh53hGGS5
 i;                 .MS5hM35MH5AhGBMMMMMMHHMMMMMMBGhA2Hh55MM2SG,                 :i
XB9Ms.             :##A3hA2h2Mh3MGBSGSSGGGGGGSSGSBGMh3M2hAA3h2#9;              rM9B2
#HH#9#A           .#GA3hA22225MGSGHMMMMMMMMMMMMMMMGSSM52222Ah3XHB.           X#9#HH9
9GHHM#5         . XBX222A2222hGGMhhMMMMh3553hMMMMhhMHGM2A22AA22X92 .         2#MHHH#
3#SHHGhhh,       .#MA2A2H2A222HGhMMMAsriiiiiirsAMMMhMS2A222H2A2Ah9.       ,hM3HHHS#h
iGBHHHS9BG,   ,r2G9A2222h2AA2A2MMMMHArsrrrirrsrAMMMMM2A2AA2h2222A#SAi.    MB9SHHH9Sr
BSHHHHG#S9Hsr5HSG#9A2222AA25A2A2533h33MhhMMMhhHh33355A2A55AA2222A#9GGM2rrh9S#SHHHHS9
HHHHHHMSB#99BSGHGGBGA2222AhHA22AAAAAGSX22ss22sGSAAAAA22AHMA2222AH&GGHGS999#BSMHHHHHH
GHHHHG5.s##G##HHA;:BhA2222222222A22G&53BhAAhB3MBS22A2222222222A3&i;2GH#9G#9A.2SHHHHH
GHHHS9A  sB9#5HM2: s&2A22222222AH5AH9S#3A22A3#S#G22H222222222AABX :2MGhS9BA  X9SHHHG
S999G;    i2ii2HGH5:M95AAA222222h5AA5H5AAMMAA5H5AA2h222222AAA5#G:2HGH2rsAr    ;H999S
 :sX       ,hH:;5HG###99G5AAAA22A222AAA2A55A2AAA222A22AAAA5H99S##SH5;,MM; .     sX:
        shX:MHM, ;hB9h.XH99H352AAAXAAAAA2AA2AAAAAXAAA253H99HX.39BM; .hHM;rMX
        AGh :MHh.  39Gr  ,XH##99#SGHM352AAAA253MHGS#99##GA,  iG9h.  3HH; 5G5
        :HH; iMGH:  2HM:     .:isA5MHS#99##99#SGM3Asi:.     :MH5  :MGHr ,MHr
         3GX  r99G. ,hH3.             .,;rr;:.             .3Hh,  H99X  rGh,
         2BS,  MBG   ;HHA..                                AHH;   MBG  ,GB3
         29Bs  sSh.   sS9G;                               29#X    5S2  iB93
         s9S.  iHM,    GB9:                              ,BBG     hHX   HB2
         AG3   ;HGi    rSS;                               5#M.   :hHs . AG5
         2H2   :h2A      ,,          .;;;::;;;,             :.,,:rrsi   XH3.
         H95 i;Ah:i,::.              rXrrsXrrsr              :rr;i;r;:; r##s
        r992.srX2rXrrs;..............r;  ,,  :r..............:rrirrsXrs.XB9s
        ;G#2,::,,:;:::,,,,,,,,,,,,,,,r2ssXXss2s,,,,,,,,,,,,,,,::::::;::,iG#X
         ,ir                          ........                           :ii

                  ONEI // ABYSSAL CRAB TITAN, RISING OVER THE CITY
""".strip("\n")

READY_SCENE = r"""
                .          *          .
          .---======================---.
          |   ONEIRODEX // GATE OPEN   |
          `---======================---'

       |[]|   |_|   |[]|     GATE     |[]|   |_|   |[]|
    ___|__|___|_|___|__|______|__|_____|_|___|__|___|__|___

       . . . . . . . . THE WORLD IS AWAKE . . . . . . . .
""".strip("\n")

RECOVERY_SCENE = r"""
         .--------------------------------.
         | FIELD NOTES // TITAN WATCH     |
         | Gate secure. Review the log.   |
         `--------------------------------'

                _..----.._
             .-'  `----'  '-.
            /   the den waits  \\
            `------------------'

       . . . . . . . . . TITAN AT REST . . . . . . . . . .
""".strip("\n")


def _write_terminal(text: str) -> None:
    """Write the pre-log artwork directly to stdout and flush it in order."""
    sys.stdout.write(text)
    sys.stdout.flush()


def print_startup_splash() -> None:
    """Print the shared masthead and character before startup begins."""
    _write_terminal(f"{MASTHEAD}\n{TITAN}\n")
    _write_terminal("  THUM... THUM... // Onei stirs beneath the black-water stone.\n\n")


def print_startup_epilogue(ready: bool) -> None:
    """Finish the startup adventure before Uvicorn begins its log stream."""
    if ready:
        _write_terminal("\nGRRROOOM! // Onei lifts the launch gate with both mighty claws!\n")
        _write_terminal("             The worlds wake beneath the watch of the deep.\n")
        _write_terminal(f"{TITAN}\n{READY_SCENE}\n")
    else:
        _write_terminal("\nLOW RRR... // Onei folds its pincers around the gate and waits.\n")
        _write_terminal("             The field notes will show us what needs repair.\n")
        _write_terminal(f"{TITAN}\n{RECOVERY_SCENE}\n")


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "splash":
        print_startup_splash()
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "ending" and sys.argv[2] in {"ready", "recovery"}:
        print_startup_epilogue(sys.argv[2] == "ready")
        return 0
    sys.stderr.write("Usage: python -m scripts.startup_art splash|ending ready|recovery\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
