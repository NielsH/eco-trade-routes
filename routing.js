//Terrain-aware travel times for the planner, from the server's own 2D map and height map.
//
//The map (/Layers/TerrainLatest.gif) colours each block column by its top solid block; terrain-colors.js says what a
//colour means (road + speed factor, natural ground + speed factor, riverbed, forest soil; anything else is a constructed
//block). The height map (/Layers/HeightMapLatest.gif) is that block's height. Water is not drawn, so it is inferred: a
//riverbed, or natural ground below sea level, has water above it. Land vehicles can't cross water unless something is
//built on top (a bridge deck shows instead of the riverbed); boats only move on water. Tunnels can't be seen from above.
//
//Off road, a cart or truck mostly can't get through: trees (not on the map, but forest soil means them) and natural
//steps of two or more blocks between neighbouring columns stop it. Those cells are made very slow rather than closed, so
//a route still exists when nothing better does but is ranked accordingly; steps of three or more (cliffs, ravine walls)
//are closed. Roads and constructed ground are exempt: someone made them drivable.
//
//Vehicles can't climb a block off road: they drive down a step, but going up needs a ramp, which is part of a road. So
//an edge that climbs (by the cells' median heights) is only open between two road cells. Edges are directed: the
//search runs from the start outwards, so downhill off road is fine and the way back up has to use roads.
//
//A short stretch off road between patches of road is fine; a long one through country with nothing resembling a road
//isn't (trees and rocks the map doesn't show, and slow going). Each cell knows how far it is from the nearest road or
//constructed ground; beyond half the allowed off-road stretch (p.stretch, blocks) it is OFFROAD_DEEP slower again, so
//a gap of up to p.stretch between two roads costs nothing extra and a cross-country leg is a last resort.
//
//The world wraps around (a torus): leaving the map on one side comes back on the other. Only boats can use that, since
//the edges are ocean; a path that crosses the seam jumps from one side of the map to the other between two cells.
//
//Land vehicle + boat ("combo"): the player packs one vehicle up and carries it in the other, so a trip can switch between
//land and water at any shore, both ways, for p.switchCost each time. The search then runs over two layers of the grid,
//land and water; water time is scaled by p.waterScale (land speed / boat speed) so all times stay "seconds at the land
//vehicle's speed 1".
//
//The world is reduced to cells of CELL x CELL blocks and searched with Dijkstra in a worker (window.Routing below).
"use strict";
(function () {
  const CELL = 4;
  const OFFROAD_FOREST = 0.15;    // forest soils without a road: trees aren't on the map but block vehicles
  const OFFROAD_STEEP = 0.15;     // off road with a natural step of STEEP_STEP blocks between neighbouring columns
  const STEEP_STEP = 2;
  const CLIFF_STEP = 3;           // off road with a step this high: impassable for land vehicles
  const OFFROAD_DEEP = 0.1;       // off road, farther than half the allowed stretch from any road or constructed ground
  const SLOPE_COST = 2;           // extra time per block climbed per block driven
  const ROUGH_COST = 3;           // off road: slowdown per block of average step inside a cell
  const FREE_RADIUS = 3;          // cells around a shop where walls/steps don't block (getting out of the building)

  //---------------------------------------------------------------- worker ----------------------------------------------------------------
  function workerMain() {
    let G = null;                                   // grid arrays from the page
    const effs = new Map();

    self.onmessage = e => {
      const m = e.data;
      try {
        if (m.type === "grid") { G = m.grid; effs.clear(); return; }
        if (m.type === "matrix") return matrix(m);
        if (m.type === "path") return path(m);
        if (m.type === "row") return row(m);
      } catch (err) { self.postMessage({ id: m.id, error: String(err && err.stack || err) }); }
    };

    //Speed factor per cell for a vehicle: 1 + (surface - 1) * roadMult on roads and paved (constructed) ground; off road
    //also x offroad, slowed by roughness and forest.
    function effFor(p) {
      const key = p.mode + "|" + p.roadMult + "|" + p.offroad + "|" + p.stretch;
      if (effs.has(key)) return effs.get(key);
      const n = G.N * G.N, e = new Float32Array(n);
      for (let c = 0; c < n; c++) {
        if (p.mode === "water") { e[c] = 1; continue; }
        const road = G.road[c];
        if (road > 0) e[c] = 1 + (road - 1) * p.roadMult;
        else if (G.paved[c]) e[c] = 1;
        else {
          let v = (1 + (G.surf[c] - 1) * p.roadMult) * p.offroad / (1 + G.ROUGH_COST * G.rough[c]);
          if (G.forest[c]) v *= G.OFFROAD_FOREST;
          if (G.maxStep[c] >= G.STEEP_STEP) v *= G.OFFROAD_STEEP;
          if (p.stretch != null && G.roadDist[c] * G.CELL > p.stretch / 2) v *= G.OFFROAD_DEEP;
          e[c] = v;
        }
        if (e[c] < 0.01) e[c] = 0.01;
      }
      effs.set(key, e);
      return e;
    }

    //Usable cells within FREE_RADIUS of c, with the cost of getting between them and c (seconds at speed 1): the stretch
    //from a shop counter to the road or dock outside. Only a search's own departure and arrival get this leeway, so
    //nearby shops can't chain into corridors through buildings or, for boats, over land.
    function near(c, ok) {
      const N = G.N, r = G.FREE_RADIUS, out = [];
      if (c < 0) return out;
      const row = (c / N) | 0, col = c % N;
      for (let dr = -r; dr <= r; dr++) for (let dc = -r; dc <= r; dc++) {
        const rr = (row + dr + N) % N, cc = (col + dc + N) % N;   // the world wraps
        const v = rr * N + cc;
        if (ok(v)) out.push([v, G.CELL * Math.hypot(dr, dc)]);
      }
      return out;
    }
    const okLand = c => G.blocked[c] === 0 && G.cliff[c] === 0, okWater = c => G.water[c] === 1;
    //The layers a search runs over, each true for water: a land vehicle, a boat, or both (combo).
    const layersFor = p => p.mode === "combo" ? [false, true] : [p.mode === "water"];
    const okIn = water => water ? okWater : okLand;

    //Binary heap of (key, node) with lazy deletion.
    function heap() {
      let keys = new Float64Array(1 << 16), nodes = new Int32Array(1 << 16), size = 0;
      return {
        get size() { return size; },
        push(k, v) {
          if (size === keys.length) { const k2 = new Float64Array(size * 2), n2 = new Int32Array(size * 2); k2.set(keys); n2.set(nodes); keys = k2; nodes = n2; }
          let i = size++;
          while (i > 0) { const p = (i - 1) >> 1; if (keys[p] <= k) break; keys[i] = keys[p]; nodes[i] = nodes[p]; i = p; }
          keys[i] = k; nodes[i] = v;
        },
        pop() {   // returns node; key in this.k
          const v = nodes[0]; this.k = keys[0];
          const k = keys[--size], n = nodes[size];
          let i = 0;
          for (;;) {
            let c = 2 * i + 1;
            if (c >= size) break;
            if (c + 1 < size && keys[c + 1] < keys[c]) c++;
            if (keys[c] >= k) break;
            keys[i] = keys[c]; nodes[i] = nodes[c]; i = c;
          }
          keys[i] = k; nodes[i] = n;
          return v;
        },
      };
    }

    //Dijkstra from every usable cell near src, over the whole grid and each layer (state = layer * n + cell). Seconds at
    //speed 1 (divide by the vehicle speed; in combo, the land vehicle's).
    function search(p, src, wantPred) {
      const N = G.N, n = N * N, e = effFor(p), layers = layersFor(p), L = layers.length;
      const waterScale = p.mode === "combo" ? p.waterScale : 1, switchCost = p.switchCost || 0;
      const dist = new Float64Array(L * n).fill(Infinity), done = new Uint8Array(L * n), pred = wantPred ? new Int32Array(L * n).fill(-1) : null;
      const h = heap();
      layers.forEach((water, li) => { for (const [c, d] of near(src, okIn(water))) if (d < dist[li * n + c]) { dist[li * n + c] = d; h.push(d, li * n + c); } });
      const D = [[-1, -1], [-1, 0], [-1, 1], [0, -1], [0, 1], [1, -1], [1, 0], [1, 1]];
      while (h.size) {
        const s = h.pop(), ds = h.k;
        if (done[s]) continue;
        done[s] = 1;
        const li = (s / n) | 0, u = s - li * n, water = layers[li], ur = (u / N) | 0, uc = u % N;
        for (const [dr, dc] of D) {
          const vr = (ur + dr + N) % N, vc = (uc + dc + N) % N;   // the world wraps
          const v = vr * N + vc, len = G.CELL * (dr && dc ? Math.SQRT2 : 1);
          for (let lj = 0; lj < L; lj++) {
            const t = lj * n + v, toWater = layers[lj];
            if (done[t] || !okIn(toWater)(v)) continue;
            let secs;
            if (lj !== li) secs = switchCost + len * (toWater ? waterScale : 1);   // at the shore: pack one vehicle into the other
            else if (water) secs = len * waterScale;
            else {
              const climb = G.h[v] - G.h[u], dh = Math.abs(climb);
              if (dh > len) continue;                                // more than one block up per block: a cliff or a wall
              if (climb >= 1 && !(G.ramp[u] && G.ramp[v])) continue;   // up a block off road: needs a ramp
              secs = len / ((e[u] + e[v]) / 2) * (1 + G.SLOPE_COST * dh / len);
            }
            const nd = ds + secs;
            if (nd < dist[t]) { dist[t] = nd; if (pred) pred[t] = s; h.push(nd, t); }
          }
        }
      }
      return { dist, pred, layers, n };
    }

    //Arrival at t: the best usable cell near it in any layer, plus the stretch to the counter. [seconds, state]
    function arrive(r, t) {
      let best = Infinity, state = -1;
      r.layers.forEach((water, li) => {
        for (const [c, d] of near(t, okIn(water))) { const v = r.dist[li * r.n + c] + d; if (v < best) { best = v; state = li * r.n + c; } }
      });
      return [best, state];
    }

    function matrix(m) {
      const n = m.cells.length, times = new Float64Array(n * n).fill(Infinity);
      for (let i = 0; i < n; i++) {
        const r = search(m.p, m.cells[i], false);
        for (let j = 0; j < n; j++) times[i * n + j] = i === j ? 0 : arrive(r, m.cells[j])[0];
        if (i % 5 === 0) self.postMessage({ id: m.id, progress: i / n });
      }
      self.postMessage({ id: m.id, times }, [times.buffer]);
    }

    function row(m) {
      const r = search(m.p, m.start, false);
      const times = Float64Array.from(m.cells, c => arrive(r, c)[0]);
      self.postMessage({ id: m.id, times }, [times.buffer]);
    }

    //The route itself: its cells, which of them are by boat, its share on roads (or constructed ground), the longest
    //stretch without one, and how often it switches vehicle.
    function path(m) {
      const r = search(m.p, m.from, true), [seconds, end] = arrive(r, m.to);
      if (!isFinite(seconds)) return self.postMessage({ id: m.id, cells: null });
      const states = [];
      for (let s = end; s !== -1; s = r.pred[s]) states.push(s);
      states.reverse();
      const cells = states.map(s => s % r.n), boat = Uint8Array.from(states, s => r.layers[(s / r.n) | 0] ? 1 : 0);
      let road = 0, run = 0, longest = 0, water = 0, switches = 0;
      cells.forEach((c, i) => {
        if (i && boat[i] !== boat[i - 1]) switches++;
        if (boat[i]) { water++; run = 0; }
        else if (G.road[c] > 0 || G.paved[c]) { road++; run = 0; }
        else longest = Math.max(longest, ++run);
      });
      const land = cells.length - water;
      self.postMessage({ id: m.id, cells, boat, onRoad: land ? road / land : 0, offroadBlocks: longest * G.CELL,
        boatShare: water / cells.length, switches, seconds });
    }
  }

  //---------------------------------------------------------------- page side ----------------------------------------------------------------
  let worker = null, grid = null, nextId = 1;
  const pending = new Map();

  function call(msg, onProgress) {
    return new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject, onProgress });
      worker.postMessage({ ...msg, id });
    });
  }

  function startWorker() {
    if (worker) return;
    const src = "(" + workerMain.toString() + ")()";
    worker = new Worker(URL.createObjectURL(new Blob([src], { type: "text/javascript" })));
    worker.onmessage = e => {
      const m = e.data, p = pending.get(m.id);
      if (!p) return;
      if (m.progress != null) { p.onProgress?.(m.progress); return; }
      pending.delete(m.id);
      if (m.error) p.reject(new Error(m.error)); else p.resolve(m);
    };
  }

  function pixels(img) {
    const c = document.createElement("canvas");
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const g = c.getContext("2d", { willReadFrequently: true });
    g.drawImage(img, 0, 0);
    return g.getImageData(0, 0, c.width, c.height).data;   // needs CORS (the server sends Access-Control-Allow-Origin: *)
  }

  //Reduce the map to cells. A cell with any water pixel blocks land vehicles unless it also holds a road or a
  //constructed block (a bridge deck): conservative, so a thin river can't slip between cells.
  function buildGrid(terrainImg, heightImg, seaLevel, colors) {
    const size = terrainImg.naturalWidth, N = Math.floor(size / CELL);
    const tp = pixels(terrainImg), hp = pixels(heightImg);
    const hexInt = h => parseInt(h, 16);
    const road = new Map(Object.entries(colors.road).map(([k, v]) => [hexInt(k), v]));
    const natural = new Map(Object.entries(colors.natural).map(([k, v]) => [hexInt(k), v]));
    const riverbed = new Set(colors.riverbed.map(hexInt)), forestSet = new Set(colors.forest.map(hexInt));
    const n = N * N;
    const g = { N, CELL, SLOPE_COST, ROUGH_COST, OFFROAD_FOREST, OFFROAD_STEEP, STEEP_STEP, OFFROAD_DEEP, FREE_RADIUS,
      h: new Float32Array(n), road: new Float32Array(n), surf: new Float32Array(n), rough: new Float32Array(n),
      forest: new Uint8Array(n), paved: new Uint8Array(n), blocked: new Uint8Array(n), water: new Uint8Array(n),
      maxStep: new Uint8Array(n), cliff: new Uint8Array(n), roadDist: new Uint16Array(n) };
    //Per pixel: the largest height step to a neighbouring column, where both are natural dry ground (a step onto a
    //road, a wall or into water says nothing about how rough the land is).
    const nat = new Uint8Array(size * size), pxStep = new Uint8Array(size * size);
    for (let px = 0; px < size * size; px++) {
      const i = px * 4, nEff = natural.get((tp[i] << 16) | (tp[i + 1] << 8) | tp[i + 2]);
      nat[px] = nEff !== undefined && hp[i] >= seaLevel ? 1 : 0;
    }
    for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
      const px = y * size + x;
      if (!nat[px]) continue;
      for (const q of [x + 1 < size ? px + 1 : -1, y + 1 < size ? px + size : -1]) {
        if (q < 0 || !nat[q]) continue;
        const d = Math.abs(hp[px * 4] - hp[q * 4]);
        if (d > pxStep[px]) pxStep[px] = d;
        if (d > pxStep[q]) pxStep[q] = d;
      }
    }
    const hs = new Float32Array(CELL * CELL);
    for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) {
      let roadEff = 0, surf = 0, land = 0, waterPx = 0, deck = 0, constructed = 0, forest = 0, step = 0, maxStep = 0, k = 0;
      for (let y = 0; y < CELL; y++) for (let x = 0; x < CELL; x++) {
        const px = (r * CELL + y) * size + (c * CELL + x), i = px * 4;
        if (pxStep[px] > maxStep) maxStep = pxStep[px];
        const rgb = (tp[i] << 16) | (tp[i + 1] << 8) | tp[i + 2], ht = hp[i];
        hs[k++] = ht;
        if (x > 0) step += Math.abs(ht - hp[i - 4]);
        if (y > 0) step += Math.abs(ht - hp[i - size * 4]);
        const rEff = road.get(rgb), nEff = natural.get(rgb);
        const isWater = riverbed.has(rgb) || (nEff !== undefined && ht < seaLevel);
        if (isWater) { waterPx++; continue; }
        land++;
        if (rEff !== undefined) { roadEff = Math.max(roadEff, rEff); surf += rEff; deck++; }
        else if (nEff !== undefined) { surf += nEff; if (forestSet.has(rgb)) forest++; }
        else { surf += 1; constructed++; deck++; }
      }
      const cell = r * N + c;
      hs.sort(); g.h[cell] = (hs[7] + hs[8]) / 2;
      g.rough[cell] = step / (2 * CELL * (CELL - 1));
      g.road[cell] = roadEff;
      g.surf[cell] = land ? surf / land : 1;
      g.forest[cell] = forest * 2 >= CELL * CELL ? 1 : 0;
      g.paved[cell] = constructed * 2 >= CELL * CELL ? 1 : 0;
      g.water[cell] = waterPx * 2 >= CELL * CELL ? 1 : 0;
      g.blocked[cell] = waterPx > 0 && deck === 0 ? 1 : 0;
      g.maxStep[cell] = maxStep;
      g.cliff[cell] = maxStep >= CLIFF_STEP && roadEff === 0 && !g.paved[cell] ? 1 : 0;
    }
    g.ramp = new Uint8Array(n);   // roads and constructed ground: where a climb can be made (ramps, built slopes)
    for (let c = 0; c < n; c++) g.ramp[c] = g.road[c] > 0 || g.paved[c] ? 1 : 0;
    //Cells to the nearest road or constructed ground (breadth-first from all of them at once; the world wraps).
    const queue = new Int32Array(n);
    let head = 0, tail = 0;
    g.roadDist.fill(65535);
    for (let c = 0; c < n; c++) if (g.road[c] > 0 || g.paved[c]) { g.roadDist[c] = 0; queue[tail++] = c; }
    while (head < tail) {
      const u = queue[head++], ur = (u / N) | 0, uc = u % N, d = g.roadDist[u] + 1;
      for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) {
        if (!dr && !dc) continue;
        const v = ((ur + dr + N) % N) * N + (uc + dc + N) % N;
        if (g.roadDist[v] > d) { g.roadDist[v] = d; queue[tail++] = v; }
      }
    }
    return g;
  }

  const cellOf = (x, z, size) => {
    if (!grid) return -1;
    const col = Math.floor(x / CELL), row = Math.floor((size - 1 - z) / CELL);   // map row 0 = north (high z)
    return row >= 0 && row < grid.N && col >= 0 && col < grid.N ? row * grid.N + col : -1;
  };
  const centerOf = (cell, size) => ({ x: (cell % grid.N) * CELL + CELL / 2, z: size - 1 - (Math.floor(cell / grid.N) * CELL + CELL / 2) });

  let size = 2000, matrixCache = new Map(), pathCache = new Map();

  window.Routing = {
    get ready() { return !!grid; },
    //Builds the grid; call again whenever the map images are reloaded.
    setup(terrainImg, heightImg, seaLevel) {
      if (!window.TERRAIN_COLORS) throw new Error("terrain-colors.js missing");
      startWorker();
      size = terrainImg.naturalWidth;
      grid = buildGrid(terrainImg, heightImg, seaLevel, window.TERRAIN_COLORS);
      worker.postMessage({ type: "grid", grid });
      matrixCache = new Map(); pathCache = new Map();
    },
    //Seconds at speed 1 between every pair of points (row-major n x n), Infinity when unreachable. Cached per input.
    async matrix(p, points, onProgress) {
      const cells = points.map(q => cellOf(q.x, q.z, size)), key = JSON.stringify([p, cells]);
      if (!matrixCache.has(key)) matrixCache.set(key, call({ type: "matrix", p, cells }, onProgress));
      const r = await matrixCache.get(key);
      return { times: r.times, n: cells.length };
    },
    //Seconds at speed 1 from one point to each of `points`.
    async row(p, start, points) {
      const cells = points.map(q => cellOf(q.x, q.z, size)), sc = cellOf(start.x, start.z, size), key = JSON.stringify(["row", p, sc, cells]);
      if (!matrixCache.has(key)) matrixCache.set(key, call({ type: "row", p, start: sc, cells }));
      return (await matrixCache.get(key)).times;
    },
    //The route between two points as world coordinates, with its share on roads or paved ground.
    async path(p, a, b) {
      const from = cellOf(a.x, a.z, size), to = cellOf(b.x, b.z, size), key = JSON.stringify([p, from, to]);
      if (!pathCache.has(key)) pathCache.set(key, call({ type: "path", p, from, to }));
      const r = await pathCache.get(key);
      if (!r.cells) return null;
      const boat = [r.boat[0] || 0, ...r.boat, r.boat[r.boat.length - 1] || 0];   // per point: by boat (the ends take their neighbour's)
      return { points: [a, ...r.cells.map(c => centerOf(c, size)), b], boat, onRoad: r.onRoad, offroadBlocks: r.offroadBlocks,
        boatShare: r.boatShare, switches: r.switches, seconds: r.seconds };
    },
  };
})();
