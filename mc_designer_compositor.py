#!/usr/bin/env python3
"""
mc-designer integration for comic-cli page composition.

Provides high-level interface to mc-designer for full-page comic composition.
Leverages mc-designer's canvas, layer positioning, and stylization capabilities.

Usage:
    from mc_designer_compositor import composite_with_mc_designer
    
    result = composite_with_mc_designer(
        panel_images=[Path("panel1.png"), Path("panel2.png"), ...],
        layout=[(1, [1, 1])],  # Grid layout
        captions=["Caption 1", "Caption 2"],
        style="ligne-claire",
        output_path=Path("output.png")
    )
"""

import os
import sys
import json
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Any

# PIL for panel analysis
try:
    from PIL import Image
except ImportError:
    print("pip install pillow")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Canvas & Layer Positioning Utilities
# ---------------------------------------------------------------------------

def calculate_grid_layout(panel_images: List[Path], 
                         cols: int = 2) -> Tuple[int, int, List[Tuple[int, int]]]:
    """
    Calculate optimal canvas size and layer positions for panel grid.
    
    Returns:
        (canvas_width, canvas_height, layer_positions)
        where layer_positions is list of (x, y) tuples for each panel
    """
    if not panel_images:
        return 1024, 1024, []
    
    # Load panel dimensions
    panel_dims = []
    for panel_path in panel_images:
        if panel_path.exists():
            try:
                img = Image.open(panel_path)
                panel_dims.append(img.size)  # (width, height)
            except Exception as e:
                print(f"  [!] Failed to load {panel_path}: {e}")
                panel_dims.append((512, 512))
        else:
            panel_dims.append((512, 512))
    
    # Grid layout calculation
    rows = (len(panel_dims) + cols - 1) // cols  # Ceiling division
    
    # Assume uniform panel size for simplicity (use first panel as reference)
    panel_w, panel_h = panel_dims[0]
    
    # Calculate canvas with gutters
    gutter = 18
    margin = 48
    canvas_w = margin * 2 + (cols * panel_w) + (gutter * (cols - 1))
    canvas_h = margin * 2 + (rows * panel_h) + (gutter * (rows - 1))
    
    # Calculate layer positions (x, y) for each panel
    layer_positions = []
    for idx, (pw, ph) in enumerate(panel_dims):
        row = idx // cols
        col = idx % cols
        x = margin + (col * (pw + gutter))
        y = margin + (row * (ph + gutter))
        layer_positions.append((x, y))
    
    return canvas_w, canvas_h, layer_positions


def create_mc_designer_canvas(canvas_name: str, 
                             width: int, 
                             height: int,
                             style: str = "ligne-claire") -> bool:
    """
    Create an mc-designer canvas via CLI.
    
    Usage: miniclaw mc-designer create-canvas --name comic-page-001 --width 1988 --height 3075
    """
    try:
        cmd = [
            "miniclaw", "mc-designer", "create-canvas",
            "--name", canvas_name,
            "--width", str(width),
            "--height", str(height)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"  [!] Canvas creation failed: {result.stderr}")
            return False
        print(f"  ✓ Canvas created: {canvas_name}")
        return True
    except Exception as e:
        print(f"  [!] Canvas creation error: {e}")
        return False


def add_layer_to_canvas(canvas_name: str,
                       layer_name: str,
                       image_path: Path,
                       x: int,
                       y: int) -> bool:
    """
    Add an image layer to an mc-designer canvas at specified position.
    
    Usage: miniclaw mc-designer add-layer --canvas comic-page-001 --layer panel-1 --image panel1.png --x 48 --y 48
    """
    try:
        cmd = [
            "miniclaw", "mc-designer", "add-layer",
            "--canvas", canvas_name,
            "--layer", layer_name,
            "--image", str(image_path),
            "--x", str(x),
            "--y", str(y)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"  [!] Layer add failed: {result.stderr}")
            return False
        print(f"  ✓ Layer added: {layer_name}")
        return True
    except Exception as e:
        print(f"  [!] Layer add error: {e}")
        return False


def composite_with_mc_designer(panel_images: List[Path],
                              layout: List[Tuple],
                              captions: List[str],
                              style: str = "ligne-claire",
                              output_path: Path = None) -> Optional[Path]:
    """
    Composite panels into a full comic page using mc-designer.
    
    Args:
        panel_images: List of paths to panel images
        layout: Grid layout spec [(row_weight, [col_weights, ...]), ...]
        captions: List of caption strings
        style: Style name (ligne-claire, rorschach, noir)
        output_path: Where to save final composite
    
    Returns:
        Path to output file, or None on failure
    """
    if not output_path:
        output_path = Path("/tmp/comic-page.png")
    
    # Step 1: Calculate canvas dimensions and layer positions
    canvas_w, canvas_h, positions = calculate_grid_layout(panel_images, cols=2)
    
    # Step 2: Create canvas in mc-designer
    canvas_name = f"comic-page-{Path(output_path).stem}"
    if not create_mc_designer_canvas(canvas_name, canvas_w, canvas_h, style):
        print(f"  [!] Failed to create canvas {canvas_name}")
        return None
    
    # Step 3: Add panel layers
    for idx, (panel_path, (x, y)) in enumerate(zip(panel_images, positions)):
        if not panel_path.exists():
            print(f"  [!] Panel not found: {panel_path}")
            continue
        
        layer_name = f"panel-{idx}"
        if not add_layer_to_canvas(canvas_name, layer_name, panel_path, x, y):
            print(f"  [!] Failed to add layer {layer_name}")
            continue
        
        print(f"  ✓ Panel {idx+1} positioned at ({x}, {y})")
    
    # Step 4: Apply style and render
    print(f"  ➜ Rendering composite: {canvas_name}")
    try:
        # Export the canvas to PNG
        cmd = [
            "miniclaw", "mc-designer", "export",
            "--canvas", canvas_name,
            "--format", "png",
            "--output", str(output_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"  [!] Composite failed: {result.stderr}")
            return None
        
        if output_path.exists():
            print(f"  ✓ Composite rendered: {output_path}")
            return output_path
        else:
            print(f"  [!] Output file not created: {output_path}")
            return None
    except Exception as e:
        print(f"  [!] Render error: {e}")
        return None


def composite_with_captions(panel_images: List[Path],
                           layout: List[Tuple],
                           captions: List[str],
                           style: str = "ligne-claire",
                           output_path: Path = None) -> Optional[Path]:
    """
    Composite panels with styled caption boxes using mc-designer.
    
    This is the full-featured version that adds styled captions on top
    of the base panel composite.
    """
    # First, create base composite without captions
    base_path = Path(tempfile.gettempdir()) / f"comic-base-{Path(output_path or 'output').stem}.png"
    
    if not composite_with_mc_designer(panel_images, layout, [], style, base_path):
        return None
    
    # TODO: Add caption rendering layer here (second pass with PIL + styled boxes)
    # For now, return the base composite
    
    if output_path and output_path != base_path:
        base_path.rename(output_path)
        return output_path
    
    return base_path


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------

def composite_page_pil(panel_images: List[Path], layout: List[Tuple],
                      output_path: Path, captions: List[str],
                      style: dict = None) -> Path:
    """
    Fallback to PIL-based composite (for backwards compatibility).
    
    Note: This is a placeholder. The actual PIL implementation lives in am_blog_build.py
    """
    from PIL import Image, ImageDraw, ImageOps
    
    # Use defaults from am_blog_build
    PAGE_W = 1988
    PAGE_H = 3075
    MARGIN = 48
    GUTTER = 18
    BORDER_W = 4
    
    if style is None:
        style = {"page_bg": (13, 13, 26), "panel_border": (220, 180, 80)}
    
    page = Image.new("RGB", (PAGE_W, PAGE_H), style["page_bg"])
    
    total_h_weight = sum(w for w, _ in layout)
    usable_h = PAGE_H - 2 * MARGIN - GUTTER * (len(layout) - 1)
    
    panel_idx = 0
    y = MARGIN
    
    for row_weight, col_weights in layout:
        row_h = int(usable_h * row_weight / total_h_weight)
        total_c_weight = sum(col_weights)
        usable_w = PAGE_W - 2 * MARGIN - GUTTER * (len(col_weights) - 1)
        x = MARGIN
        
        for col_weight in col_weights:
            cell_w = int(usable_w * col_weight / total_c_weight)
            cell_h = row_h
            
            crop_anchor = (0.5, 0.0) if (panel_idx % 2 == 0) else (0.5, 1.0)
            if panel_idx < len(panel_images) and panel_images[panel_idx].exists():
                try:
                    panel_img = Image.open(panel_images[panel_idx]).convert("RGB")
                    panel_img = ImageOps.fit(panel_img, (cell_w, cell_h),
                                            Image.LANCZOS, centering=crop_anchor)
                except Exception as e:
                    print(f"  [!] Panel load failed: {e}")
                    panel_img = Image.new("RGB", (cell_w, cell_h), (25, 25, 35))
            else:
                panel_img = Image.new("RGB", (cell_w, cell_h), (25, 25, 35))
            
            page.paste(panel_img, (x, y))
            
            # Simple border for now
            draw = ImageDraw.Draw(page)
            draw.rectangle(
                [x, y, x + cell_w - 1, y + cell_h - 1],
                outline=style["panel_border"],
                width=BORDER_W
            )
            
            x += cell_w + GUTTER
            panel_idx += 1
        
        y += row_h + GUTTER
    
    page.save(output_path, "PNG", dpi=(300, 300))
    print(f"  ✓ Page saved (PIL) → {output_path}")
    return output_path


if __name__ == "__main__":
    # Simple test
    print("mc_designer_compositor — comic page composition module")
    print("Usage: import and call composite_with_mc_designer()")
