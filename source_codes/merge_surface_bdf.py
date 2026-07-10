import os

# Input files
volume_file = "castem_mesh_v.bdf"
surface_files = [
    "castem_mesh_surf_min.bdf",
    "castem_mesh_surf_max.bdf",
    "castem_mesh_surf_xmin.bdf",
    "castem_mesh_surf_xmax.bdf",
    "castem_mesh_surf_ymin.bdf",
    "castem_mesh_surf_ymax.bdf",
    "castem_mesh_surf_trou_1.bdf",
    "castem_mesh_surf_trou_2.bdf",
]

# Variables for output filename
ti = "60"
crpa = "1"
smfa = "5"
numspa = "50"
opmin = "1"

output_file = f"combined_mesh_ti{ti}_crpa{crpa}_smfa{smfa}_numsp{numspa}_opmin{opmin}.bdf"

def read_bdf_lines(filename):
    with open(filename, "r") as f:
        return f.readlines()

def filter_bulk_data(lines):
    """Remove BEGIN BULK, MAT1, GRID, ENDDATA lines"""
    filtered = []
    for line in lines:
        if line.strip().startswith(("BEGIN BULK", "MAT1", "GRID", "ENDDATA")):
            continue
        filtered.append(line)
    return filtered

# ---- Step 1: Read volume ----
vol_lines = read_bdf_lines(volume_file)
vol_lines = [l for l in vol_lines if not l.strip().startswith("ENDDATA")]

# ---- Step 2: Open output ----
with open(output_file, "w") as fout:
    fout.writelines(vol_lines)

    current_elem_id = 0
    current_pshell_id = 0  # so first increment gives 0

    # ---- Step 3: Add surfaces ----
    for surf_file in surface_files:
        current_pshell_id += 1

        surf_lines = read_bdf_lines(surf_file)
        surf_filtered = filter_bulk_data(surf_lines)

        # Write PSHELL line first
        fout.write(
            f"PSHELL{current_pshell_id:>9}       1 1.0{' ' * 44}SHL{current_pshell_id:05d}\n"
        )

        # Process CQUAD4 lines
        for line in surf_filtered:
            if line.strip().startswith("CQUAD4"):
                parts = line.split()
                current_elem_id += 1
                parts[1] = str(current_elem_id)            # new CQUAD4 ID
                parts[2] = str(current_pshell_id)          # PSHELL ID
                new_line = "{:<8s}{:>8s}{:>8s}{:>8s}{:>8s}{:>8s}{:>8s}\n".format(*parts)
                fout.write(new_line)

    # ---- Step 4: End marker ----
    fout.write("ENDDATA\n")

# # ---- Step 5: Remove surface files ----
# for surf_file in surface_files:
#     try:
#         os.remove(surf_file)
#     except OSError as e:
#         print(f"Warning: could not remove {surf_file}: {e}")

print(f"✅ Combined BDF written to {output_file}")
