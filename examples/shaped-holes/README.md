# Hole-shape examples

[`all-shapes.ini`](all-shapes.ini) places one separated example of every supported shape on the documented CSV geometry:

| Shape | INI specification | Active parameters |
|---|---|---|
| Circle | `circle, cx, cy, radius` | center, radius |
| Rectangle | `rectangle, cx, cy, width, height, rotation_degrees` | center, width, height, rotation |
| Equilateral triangle | `triangle, cx, cy, side_length, rotation_degrees` | center, side length, rotation |
| Regular polygon | `regular_polygon, cx, cy, sides, circumradius, rotation_degrees` | center, integer side count ≥ 3, circumradius, rotation |

Positive rotations are counter-clockwise. For a rectangle, zero degrees aligns width with +X. For a triangle or regular polygon, zero degrees places the first vertex on +X.

Validate the complete gallery without starting Cast3M:

```powershell
python -B castem_pipeline_gui_scientific.py --headless examples\shaped-holes\all-shapes.ini --validate-only
```

Generate the real mesh:

```powershell
python -B castem_pipeline_gui_scientific.py --headless examples\shaped-holes\all-shapes.ini
python -B scripts\verify_shape_interfaces.py
```

With the optional visual requirements installed, recreate the committed real-BDF image:

```powershell
python -B scripts\render_mesh.py --bdf _runtime\all-hole-shapes\castem_mesh_v.bdf --output docs\assets\all-hole-shapes-mesh.png --title "Cast3M conformal circle, rectangle, triangle, and hexagon mesh" --view top
```

To run only one shape, copy the INI and retain only its corresponding `holeN` line. The GUI provides the same data through **Load all shape examples**; selecting a row's shape changes its active size fields.

The Python mode projects the refined square contour onto each star-shaped boundary. It uses the same angular count on the square side and the hole-wall side of every annular fill. Non-circular shapes are intentionally unavailable in the preserved reference mode and the preserved FISS calculation.
