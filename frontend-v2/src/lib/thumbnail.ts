import {API_BASE_URL} from "@/lib/config";
import type {ThumbnailRef} from "@/types/thumbnail";
export function thumbnailSrc(ref: ThumbnailRef | undefined): string | null {
  if (!ref || !Number.isInteger(ref.width) || !Number.isInteger(ref.height) || ref.width <= 0 || ref.height <= 0
      || ref.width > 8192 || ref.height > 8192 || !Number.isInteger(ref.bytes) || ref.bytes <= 0
      || !/^[a-f0-9]{64}$/.test(ref.hash)) return null;
  const expected = new RegExp(`^/api/v1/thumbnails/${ref.hash}\\.webp\\?expires=[0-9]+&sig=[a-f0-9]{64}$`);
  return expected.test(ref.url) ? `${API_BASE_URL}${ref.url}` : null;
}

