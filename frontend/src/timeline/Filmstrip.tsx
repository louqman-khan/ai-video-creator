import type { FilmMeta } from "../api/types";
import { filmSlots } from "./layout";

interface Props {
  url: string;
  meta: FilmMeta;
  inSec: number;
  clipLeftPx: number;
  clipWidthPx: number;
  pps: number;
  scrollLeft: number;
  viewportPx: number;
  height: number;
}

/** Thumbnails at their natural shape, each slot showing the frame nearest to its time. Only on-screen slots exist. */
export function Filmstrip({ url, meta, inSec, clipLeftPx, clipWidthPx, pps, scrollLeft, viewportPx, height }: Props) {
  const scale = height / meta.thumb_height;
  const tileW = Math.max(8, Math.round(meta.thumb_width * scale));
  const slots = filmSlots({ clipLeftPx, clipWidthPx, inPointSec: inSec, pps, interval: meta.interval, count: meta.count, tilePx: tileW, scrollLeft, viewportPx });
  return (
    <div className="tl-film" aria-hidden="true">
      {slots.map((s) => (
        <span
          key={s.x}
          className="tl-tile"
          style={{
            left: s.x, width: Math.min(tileW, clipWidthPx - s.x), height,
            backgroundImage: `url("${url}")`,
            backgroundSize: `${meta.count * meta.thumb_width * scale}px ${height}px`,
            backgroundPosition: `${-s.index * meta.thumb_width * scale}px 0`,
          }}
        />
      ))}
    </div>
  );
}
