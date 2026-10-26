-- Blueprint v4 Fase 11 (ADR-055): the canvas is a 2D board (Miro/Figma style). Cards get a size of their own, and the owner can put
-- free objects on it — notes, text, shapes, frames — which live in the node itself ('obj:<id>' + props). Links can carry an arrow and a style.
ALTER TABLE canvas_nodes
    ADD COLUMN w     real CHECK (w IS NULL OR w BETWEEN 60 AND 4000),
    ADD COLUMN h     real CHECK (h IS NULL OR h BETWEEN 40 AND 4000),
    ADD COLUMN props jsonb NOT NULL DEFAULT '{}';

ALTER TABLE canvas_edges
    ADD COLUMN style jsonb NOT NULL DEFAULT '{}';   -- {"to": <node id the arrow points at>, "dash": bool, "color": "#rrggbb"}
