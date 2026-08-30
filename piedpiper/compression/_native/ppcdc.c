/*
 * ppcdc.c - native boundary scan for the canonical chunker.
 *
 * Implements exactly the definition in chunking.py:
 *   H[i] = sum(k=0..63) GEAR[b[i-k]] << k   (mod 2^64, continuous over the
 *                                            whole stream, never reset at a cut)
 *   boundary at i when the active mask test passes and i >= pos + min_size
 *   forced boundary when the chunk reaches max_size
 *
 * The shift-and-add recurrence h = (h << 1) + GEAR[b] produces exactly that
 * sum: terms older than 64 bytes have been shifted out of the register. No
 * masking needed - uint64 overflow is the modulus.
 *
 * tests/test_chunking.py cross-checks this against the Python reference on
 * random and structured input. Do not "optimise" the recurrence without
 * re-running it.
 *
 * Build: see build_native.py (invoked from the Dockerfile).
 */

#include <stddef.h>
#include <stdint.h>

/* Returns the number of chunk lengths written to out_lengths, or (size_t)-1
 * if out_cap was too small. Callers size out_cap at n/min_size + 2, which is
 * a hard upper bound on the chunk count. */
size_t pp_chunk(const uint8_t *data, size_t n, const uint8_t *ctx,
                size_t ctx_len, const uint64_t *gear, uint64_t mask_s,
                uint64_t mask_l, size_t min_size, size_t avg_size,
                size_t max_size, uint32_t *out_lengths, size_t out_cap) {
  uint64_t h = 0;
  size_t pos = 0, count = 0, i;

  /* Prime the register with preceding context so a read-buffer boundary can
   * never influence a cut. Anything older than 64 bytes is irrelevant. */
  if (ctx_len > 63) {
    ctx += ctx_len - 63;
    ctx_len = 63;
  }
  for (i = 0; i < ctx_len; i++) {
    h = (h << 1) + gear[ctx[i]];
  }

  for (i = 0; i < n; i++) {
    size_t len;
    h = (h << 1) + gear[data[i]];
    len = i - pos + 1;

    if (len <= min_size) {
      continue;
    }

    if (len <= avg_size ? !(h & mask_s) : (!(h & mask_l) || len >= max_size)) {
      if (count >= out_cap) {
        return (size_t)-1;
      }
      out_lengths[count++] = (uint32_t)len;
      pos = i + 1;
    }
  }

  if (pos < n) {
    if (count >= out_cap) {
      return (size_t)-1;
    }
    out_lengths[count++] = (uint32_t)(n - pos);
  }
  return count;
}
