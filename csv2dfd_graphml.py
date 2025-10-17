"""Generate a yEd-compatible GraphML file from DFD CSV definitions.

This utility consumes three CSV files located in the `csv/` directory:

* `formato.csv`: styling metadata (shape and color) for each logical type.
* `entidades.csv`: catalog of processes, external entities, and data stores.
* `flujo.csv`: directed flows between those entities segmented by DFD level.

The script builds a primitive diagram in GraphML where every flow is rendered
as an intermediate hexagonal node. Each flow node receives undirected lines
from its emitter and a directed arrow towards its receiver, matching the
manual conventions used in yEd for the Level 1 diagram.

Usage examples (run from the repository root):

    python DFD/csv2dfd_graphml.py --nivel 1
    python DFD/csv2dfd_graphml.py --nivel 2 --output DFD/GraphML/DFD-Nivel2-auto.graphml

The output can be opened and refined within yEd. Layout coordinates are kept
simple on purpose; consider applying yEd's automatic layout tools for a
polished presentation.

---

Author: Emmanuel Nicolás Velásquez Muñoz
Institution: Universidad de Magallanes
Department: Departamento de Ingeniería en Computación
Program: Ingeniería Civil en Computación e Informática
Course: DSIA1 - Desarrollo de Sistemas de Información 1
Instructor: Dra. Patricia Maldonado

This code was developed with assistance from GitHub Copilot, an AI-powered
coding assistant. The resulting code is a product of collaboration between
the human developer and the AI assistant.

This project is open-source and available for free use, modification, and
distribution without requirement for personal attribution to the author.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from xml.sax.saxutils import escape


@dataclass
class VisualStyle:
    shape: str
    color: str
    description: str


@dataclass
class Node:
    node_id: str
    code: str
    label: str
    style: VisualStyle
    x: float
    y: float
    width: float
    height: float


@dataclass
class Edge:
    edge_id: str
    source: str
    target: str
    arrow_target: str


TYPE_MAP = {
    "P": "P",  # Proceso
    "E": "E",  # Entidad externa
    "D": "D",  # Almacén de datos (códigos D* en CSV)
}


FLOW_STYLE_MAP: Dict[Tuple[str, str], str] = {
    ("P", "P"): "PfP",
    ("P", "E"): "PfE",
    ("E", "P"): "EfP",
    ("P", "D"): "PfD",
    ("D", "P"): "DfP",
}


GEOMETRY_BY_SHAPE = {
    "ellipse": (180.0, 80.0),
    "rectangle": (180.0, 80.0),
    "trapezoid": (190.0, 90.0),
    "hexagon": (200.0, 100.0),
}


TYPE_COLUMNS = {"E": 0, "P": 1, "D": 2}
COLUMN_SPACING = 260.0
ROW_SPACING = 140.0


def resolve_code_type(code: str) -> str:
    if not code:
        raise ValueError("Código de entidad vacío no es válido")
    try:
        return TYPE_MAP[code[0]]
    except KeyError as exc:
        raise ValueError(f"Código de entidad '{code}' no reconocido") from exc


def load_styles(csv_path: Path) -> Dict[str, VisualStyle]:
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        styles: Dict[str, VisualStyle] = {}
        for row in reader:
            tipo = row["tipo"].strip()
            styles[tipo] = VisualStyle(
                shape=row["forma"].strip(),
                color=row["color"].strip(),
                description=row.get("Descripción", "").strip().strip('"'),
            )
        return styles


def load_entities(csv_path: Path) -> Dict[str, str]:
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        entities: Dict[str, str] = {}
        for row in reader:
            code = row["quien"].strip()
            name = row["Nombre"].strip().strip('"')
            entities[code] = name
        return entities


def build_entity_nodes(
    entities: Dict[str, str],
    styles: Dict[str, VisualStyle],
    active_codes: Iterable[str],
) -> Tuple[List[Node], Dict[str, Node]]:
    by_type_counter: Dict[str, int] = defaultdict(int)
    nodes_list: List[Node] = []
    nodes_map: Dict[str, Node] = {}
    for index, code in enumerate(sorted(active_codes, key=str.lower)):
        name = entities.get(code)
        if name is None:
            raise ValueError(f"La entidad '{code}' no está definida en entidades.csv")
        type_prefix = resolve_code_type(code)
        style = styles.get(type_prefix)
        if not style:
            raise ValueError(f"No hay estilo definido para el tipo '{type_prefix}'")
        column = TYPE_COLUMNS[type_prefix]
        row_index = by_type_counter[type_prefix]
        by_type_counter[type_prefix] += 1
        width, height = GEOMETRY_BY_SHAPE.get(style.shape, (180.0, 80.0))
        x = column * COLUMN_SPACING
        y = row_index * ROW_SPACING
        label = f"{code}\n{name}"
        node = Node(
            node_id=f"n{index}",
            code=code,
            label=label,
            style=style,
            x=x,
            y=y,
            width=width,
            height=height,
        )
        nodes_list.append(node)
        nodes_map[code] = node
    return nodes_list, nodes_map


def infer_flow_style(styles: Dict[str, VisualStyle], source_code: str, target_code: str) -> VisualStyle:
    src_type = TYPE_MAP.get(source_code[0])
    dst_type = TYPE_MAP.get(target_code[0])
    if not src_type or not dst_type:
        raise ValueError(f"No se puede inferir el tipo de flujo entre '{source_code}' y '{target_code}'")
    flow_key = FLOW_STYLE_MAP.get((src_type, dst_type))
    if not flow_key:
        raise ValueError(f"No existe estilo de flujo para la combinación {src_type}->{dst_type}")
    try:
        return styles[flow_key]
    except KeyError as exc:
        raise ValueError(f"El estilo '{flow_key}' no está definido en formato.csv") from exc


def load_flows(csv_path: Path, nivel: int) -> List[Dict[str, str]]:
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        return [row for row in reader if int(row["nivel"].strip()) == nivel]


def wrap_text(text: str, max_chars: int = 32) -> str:
    """Envuelve texto en múltiples líneas balanceadas sin cortar palabras.
    
    Utiliza un algoritmo de programación dinámica que minimiza el espacio no
    utilizado en cada línea, creando un resultado visualmente equilibrado.
    
    Args:
        text: El texto a envolver
        max_chars: Número máximo de caracteres por línea (por defecto 32)
    
    Returns:
        Texto con saltos de línea insertados de forma balanceada
    """
    if len(text) <= max_chars:
        return text
    
    words = text.split()
    if not words:
        return text
    
    n = len(words)
    
    # Calcular el costo (penalización) de cada posible línea
    # cost[i][j] = costo de poner words[i:j+1] en una línea
    INF = float('inf')
    line_cost = [[INF] * n for _ in range(n)]
    
    for i in range(n):
        length = 0
        for j in range(i, n):
            if i == j:
                length = len(words[j])
            else:
                length += 1 + len(words[j])  # +1 por el espacio
            
            if length <= max_chars:
                # Penalización cuadrática: preferimos líneas más llenas
                # Pero penalizamos más fuertemente cuando hay mucho espacio libre
                slack = max_chars - length
                # Penalización cúbica para penalizar más las líneas muy cortas
                line_cost[i][j] = slack ** 3
            else:
                line_cost[i][j] = INF
    
    # Programación dinámica para encontrar la distribución óptima
    # dp[i] = (costo mínimo) para words[0:i+1]
    dp = [INF] * n
    parent = [-1] * n
    
    for i in range(n):
        # Opción 1: toda la palabra desde el inicio en una línea
        if line_cost[0][i] != INF:
            dp[i] = line_cost[0][i]
            parent[i] = -1
        
        # Opción 2: break en algún punto anterior
        for j in range(i):
            if dp[j] != INF and line_cost[j + 1][i] != INF:
                cost = dp[j] + line_cost[j + 1][i]
                if cost < dp[i]:
                    dp[i] = cost
                    parent[i] = j
    
    # Reconstruir la solución
    breaks = []
    idx = n - 1
    while idx >= 0:
        if parent[idx] != -1:
            breaks.append(parent[idx] + 1)
        idx = parent[idx]
    
    breaks.reverse()
    
    # Construir las líneas
    lines = []
    start = 0
    for break_point in breaks:
        lines.append(' '.join(words[start:break_point]))
        start = break_point
    lines.append(' '.join(words[start:]))
    
    return '\n'.join(lines)


def sanitize_label(raw: str) -> str:
    cleaned = [segment.strip() for segment in raw.replace("\r", "\n").split(";")]
    cleaned = [segment for segment in cleaned if segment]
    if not cleaned:
        return "(sin descripción)"
    # Aplicar wrap_text a cada segmento antes de unirlos
    wrapped_segments = [wrap_text(f"- {segment}") for segment in cleaned]
    text = "\n".join(wrapped_segments)
    # Escapar caracteres especiales XML pero NO los saltos de línea
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    # Los saltos de línea quedan como están (literales)
    return text


def sanitize_entity_label(raw: str) -> str:
    # Detectar si la etiqueta tiene el patrón "CÓDIGO Nombre largo"
    # donde CÓDIGO es algo corto como "D1", "E2", "P3", etc.
    import re
    match = re.match(r'^([A-Z]\d+)\s+(.+)$', raw.strip())
    
    if match:
        # Separar código y nombre
        code = match.group(1)
        name = match.group(2)
        
        # Solo aplicar wrap_text al nombre si es largo (más de 32 caracteres)
        if len(name) > 32:
            wrapped_name = wrap_text(name)
            text = f"{code}\n{wrapped_name}"
        else:
            text = raw
    else:
        # Para etiquetas sin código, aplicar wrap_text normal
        if len(raw.strip()) > 32:
            text = wrap_text(raw)
        else:
            text = raw
    
    # Escapar caracteres especiales XML pero NO los saltos de línea
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    # Los saltos de línea quedan como están (literales)
    return text


def build_flow_nodes(
    flows: Iterable[Dict[str, str]],
    styles: Dict[str, VisualStyle],
    entity_nodes: Dict[str, Node],
    start_index: int,
) -> Tuple[List[Node], List[Edge]]:
    nodes: List[Node] = []
    edges: List[Edge] = []
    edge_counter = 0
    index = start_index
    pair_offset: Dict[Tuple[str, str], int] = defaultdict(int)

    for flow in flows:
        source_code = flow["quien"].strip()
        target_code = flow["donde"].strip()
        description = flow["Qué"].strip().strip('"')

        if source_code not in entity_nodes:
            raise ValueError(f"El emisor '{source_code}' no está definido en entidades.csv")
        if target_code not in entity_nodes:
            raise ValueError(f"El receptor '{target_code}' no está definido en entidades.csv")

        source_node = entity_nodes[source_code]
        target_node = entity_nodes[target_code]
        style = infer_flow_style(styles, source_code, target_code)
        width, height = GEOMETRY_BY_SHAPE.get(style.shape, (200.0, 100.0))

        pair_key = (source_code, target_code)
        offset_index = pair_offset[pair_key]
        pair_offset[pair_key] += 1

        # Position roughly midway with slight offset for multiple flows.
        base_x = (source_node.x + target_node.x) / 2.0
        base_y = (source_node.y + target_node.y) / 2.0
        angle = math.radians(20 * (offset_index % 6))
        radius = 40.0 * (offset_index // 3 + 1)
        x = base_x + radius * math.cos(angle)
        y = base_y + radius * math.sin(angle)

        flow_node = Node(
            node_id=f"n{index}",
            code=f"F{index}",
            label=sanitize_label(description),
            style=style,
            x=x,
            y=y,
            width=width,
            height=height,
        )
        nodes.append(flow_node)

        edges.append(
            Edge(
                edge_id=f"e{edge_counter}",
                source=source_node.node_id,
                target=flow_node.node_id,
                arrow_target="none",
            )
        )
        edge_counter += 1
        edges.append(
            Edge(
                edge_id=f"e{edge_counter}",
                source=flow_node.node_id,
                target=target_node.node_id,
                arrow_target="standard",
            )
        )
        edge_counter += 1
        index += 1

    return nodes, edges


def emit_node_xml(node: Node) -> str:
    label = sanitize_entity_label(node.label)
    return (
        f'    <node id="{node.node_id}">\n'
        f'      <data key="d6">\n'
        f'        <y:ShapeNode>\n'
        f'          <y:Geometry height="{node.height:.1f}" width="{node.width:.1f}" x="{node.x:.1f}" y="{node.y:.1f}"/>\n'
        f'          <y:Fill color="{node.style.color}" transparent="false"/>\n'
        f'          <y:BorderStyle color="#000000" type="line" width="1.0"/>\n'
        f'          <y:NodeLabel alignment="center" autoSizePolicy="content" fontFamily="Arial" fontSize="12" fontStyle="plain" hasBackgroundColor="false" hasLineColor="false" modelName="internal" modelPosition="c" textColor="#000000">{label}</y:NodeLabel>\n'
        f'          <y:Shape type="{node.style.shape}"/>\n'
        f'        </y:ShapeNode>\n'
        f'      </data>\n'
        f'    </node>'
    )


def emit_edge_xml(edge: Edge) -> str:
    return (
        f'    <edge id="{edge.edge_id}" source="{edge.source}" target="{edge.target}">\n'
        f'      <data key="d10">\n'
        f'        <y:PolyLineEdge>\n'
        f'          <y:Path sx="0.0" sy="0.0" tx="0.0" ty="0.0"/>\n'
        f'          <y:LineStyle color="#000000" type="line" width="1.0"/>\n'
        f'          <y:Arrows source="none" target="{edge.arrow_target}"/>\n'
        f'          <y:BendStyle smoothed="false"/>\n'
        f'        </y:PolyLineEdge>\n'
        f'      </data>\n'
        f'    </edge>'
    )


def write_graphml(nodes: Iterable[Node], edges: Iterable[Edge], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    node_xml = "\n".join(emit_node_xml(node) for node in nodes)
    edge_xml = "\n".join(emit_edge_xml(edge) for edge in edges)

    content = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<graphml xmlns=\"http://graphml.graphdrawing.org/xmlns\"\n"
        "         xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\"\n"
        "         xmlns:y=\"http://www.yworks.com/xml/graphml\"\n"
        "         xmlns:yed=\"http://www.yworks.com/xml/yed/3\"\n"
        "         xsi:schemaLocation=\"http://graphml.graphdrawing.org/xmlns\n"
        "         http://www.yworks.com/xml/schema/graphml/1.1/ygraphml.xsd\">\n"
        "  <key id=\"d6\" for=\"node\" yfiles.type=\"nodegraphics\"/>\n"
        "  <key id=\"d10\" for=\"edge\" yfiles.type=\"edgegraphics\"/>\n"
        "  <graph edgedefault=\"directed\" id=\"G\">\n"
        f"{node_xml}\n"
        f"{edge_xml}\n"
        "  </graph>\n"
        "  <data key=\"d7\">\n"
        "    <y:Resources/>\n"
        "  </data>\n"
        "</graphml>\n"
    )

    output_path.write_text(content, encoding="utf-8")


def attempt_write_graphml(
    nodes: Iterable[Node],
    edges: Iterable[Edge],
    output_path: Path,
    fallback_root: Path | None = None,
) -> Path:
    try:
        write_graphml(nodes, edges, output_path)
        return output_path
    except PermissionError as exc:
        if fallback_root is None:
            raise
        fallback_root.mkdir(parents=True, exist_ok=True)
        fallback_path = fallback_root / output_path.name
        print(
            f"No se pudo escribir en '{output_path}'. Se utilizará '{fallback_path}' en su lugar ({exc})."
        )
        try:
            write_graphml(nodes, edges, fallback_path)
        except PermissionError:
            raise PermissionError(
                f"No fue posible escribir ni en '{output_path}' ni en '{fallback_path}'. Verifica permisos."
            )
        return fallback_path


def generate_full_output(
    nivel: int,
    styles: Dict[str, VisualStyle],
    entities: Dict[str, str],
    flows: List[Dict[str, str]],
    output_path: Path,
) -> None:
    active_codes = {flow["quien"].strip() for flow in flows} | {flow["donde"].strip() for flow in flows}
    entity_node_list, entity_nodes_map = build_entity_nodes(entities, styles, active_codes)
    start_index = len(entity_node_list)
    flow_nodes, edges = build_flow_nodes(flows, styles, entity_nodes_map, start_index)
    all_nodes: List[Node] = entity_node_list + flow_nodes
    fallback_root = Path.home() / "DFD" / "GraphML"
    attempt_write_graphml(all_nodes, edges, output_path, fallback_root)


def generate_plates_output(
    nivel: int,
    styles: Dict[str, VisualStyle],
    entities: Dict[str, str],
    flows: List[Dict[str, str]],
    output_dir: Path,
) -> None:
    if nivel < 1:
        raise ValueError("El modo 'plates' solo está disponible desde el nivel 1")

    fallback_dir = Path.home() / "DFD" / "GraphML" / output_dir.name
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        fallback_dir.mkdir(parents=True, exist_ok=True)
        print(
            f"No se pudo crear el directorio '{output_dir}'. Se utilizará '{fallback_dir}' para almacenar los fragmentos."
        )
        output_dir = fallback_dir

    process_codes = sorted(
        {
            code
            for flow in flows
            for code in (flow["quien"].strip(), flow["donde"].strip())
            if code and resolve_code_type(code) == "P"
        },
        key=str.lower,
    )

    if not process_codes:
        raise ValueError(f"No se identificaron procesos en los flujos del nivel {nivel}")

    flows_by_process: Dict[str, List[Dict[str, str]]] = {code: [] for code in process_codes}
    core_flows: List[Dict[str, str]] = []

    for flow in flows:
        source_code = flow["quien"].strip()
        target_code = flow["donde"].strip()
        src_type = resolve_code_type(source_code)
        dst_type = resolve_code_type(target_code)

        if src_type == "P" and dst_type == "P":
            core_flows.append(flow)
            continue

        if src_type == "P" and dst_type != "P" and source_code in flows_by_process:
            flows_by_process[source_code].append(flow)
        if dst_type == "P" and src_type != "P" and target_code in flows_by_process:
            flows_by_process[target_code].append(flow)

    for process_code in process_codes:
        process_flows = flows_by_process.get(process_code, [])
        related_codes = {process_code}
        for flow in process_flows:
            source_code = flow["quien"].strip()
            target_code = flow["donde"].strip()
            if source_code != process_code and resolve_code_type(source_code) in {"E", "D"}:
                related_codes.add(source_code)
            if target_code != process_code and resolve_code_type(target_code) in {"E", "D"}:
                related_codes.add(target_code)

        entity_node_list, entity_nodes_map = build_entity_nodes(entities, styles, related_codes)
        start_index = len(entity_node_list)
        flow_nodes, edges = build_flow_nodes(process_flows, styles, entity_nodes_map, start_index)
        all_nodes: List[Node] = entity_node_list + flow_nodes
        process_output = output_dir / f"{process_code}.graphml"
        attempt_write_graphml(all_nodes, edges, process_output, fallback_dir)

    core_active_codes = set(process_codes)
    core_entity_nodes, core_entity_map = build_entity_nodes(entities, styles, core_active_codes)
    start_index = len(core_entity_nodes)
    core_flow_nodes, core_edges = build_flow_nodes(core_flows, styles, core_entity_map, start_index)
    attempt_write_graphml(core_entity_nodes + core_flow_nodes, core_edges, output_dir / "Core.graphml", fallback_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Construye un GraphML básico desde los CSV del DFD.")
    parser.add_argument("--nivel", type=int, required=True, help="Nivel del DFD a exportar (0, 1 o 2)")
    parser.add_argument(
        "--modo",
        choices=["full", "plates"],
        default="full",
        help="Modo de exportación: 'full' (archivo único) o 'plates' (carpetas por proceso, disponible desde el nivel 1)",
    )
    parser.add_argument(
        "--csv-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "csv",
        help="Directorio que contiene los CSV de entrada",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Ruta del archivo GraphML de salida",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    csv_dir: Path = args.csv_dir
    formato_csv = csv_dir / "formato.csv"
    entidades_csv = csv_dir / "entidades.csv"
    flujo_csv = csv_dir / "flujo.csv"

    if not formato_csv.exists() or not entidades_csv.exists() or not flujo_csv.exists():
        raise FileNotFoundError("Debe existir formato.csv, entidades.csv y flujo.csv en el directorio CSV especificado")

    styles = load_styles(formato_csv)
    entities = load_entities(entidades_csv)
    flows = load_flows(flujo_csv, args.nivel)

    if not flows:
        raise ValueError(f"No se encontraron flujos para el nivel {args.nivel}")

    if args.modo == "full":
        if args.output is None:
            default_name = f"DFD-Nivel{args.nivel}-auto.graphml"
            output_path = Path(__file__).resolve().parent / "GraphML" / default_name
        else:
            output_path = args.output
        generate_full_output(args.nivel, styles, entities, flows, output_path)
    else:
        if args.output is None:
            default_dir = Path(__file__).resolve().parent / "GraphML" / f"DFD-Nivel{args.nivel}-auto"
            output_dir = default_dir
        else:
            output_dir = args.output
        generate_plates_output(args.nivel, styles, entities, flows, output_dir)


if __name__ == "__main__":
    main()
