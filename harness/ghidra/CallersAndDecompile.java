// CallersAndDecompile.java - Ghidra headless post-script (Thaw-Super-DX).
// Usage: -postScript CallersAndDecompile.java <out.txt> <mode> <addr...>
//   mode "callers": for each address, list every reference to it (from address + containing function)
//   mode "decomp":  decompile the function containing each address
// @category Thaw-Super-DX

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

import java.io.PrintWriter;

public class CallersAndDecompile extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        try (PrintWriter out = new PrintWriter(a[0])) {
            DecompInterface dec = null;
            if (a[1].equals("decomp")) {
                dec = new DecompInterface();
                dec.openProgram(currentProgram);
            }
            for (int i = 2; i < a.length; i++) {
                Address addr = toAddr(Long.parseLong(a[i].replace("0x", ""), 16));
                if (dec == null) {
                    out.println("== references to " + addr);
                    for (Reference r : getReferencesTo(addr)) {
                        Function f = getFunctionContaining(r.getFromAddress());
                        out.println("  from " + r.getFromAddress() + " " + r.getReferenceType()
                                + " in " + (f == null ? "?" : f.getName() + " @ " + f.getEntryPoint()));
                    }
                } else {
                    Function f = getFunctionContaining(addr);
                    out.println("// ==== " + addr + " in " + (f == null ? "no function" : f.getName()));
                    if (f == null) continue;
                    DecompileResults r = dec.decompileFunction(f, 120, monitor);
                    out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "// failed: " + r.getErrorMessage());
                }
            }
        }
    }
}
