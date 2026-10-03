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
//The world is reduced to cells of CELL x CELL blocks and searched with Dijkstra in a worker (window.Routing below).
"use strict";
(function () {
  const CELL = 4;
  const OFFROAD_FOREST = 0.15;    // forest soils without a road: trees aren't on the map but block vehicles
  const OFFROAD_STEEP = 0.15;     // off road with a natural step of STEEP_STEP blocks between neighbouring columns
  const STEEP_STEP = 2;
  const CLIFF_STEP = 3;           // off road with a step this high: impassable for land vehicles
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
      const key = p.mode + "|" + p.roadMult + "|" + p.offroad;
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
        const rr = row + dr, cc = col + dc;
        if (rr < 0 || rr >= N || cc < 0 || cc >= N) continue;
        const v = rr * N + cc;
        if (ok(v)) out.push([v, G.CELL * Math.hypot(dr, dc)]);
      }
      return out;
    }
    const okFor = p => p.mode === "water" ? c => G.water[c] === 1 : c => G.blocked[c] === 0 && G.cliff[c] === 0;

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

    //Dijkstra from every usable cell near src, over the whole grid. Seconds at speed 1 (divide by the vehicle speed).
    function search(p, src, wantPred) {
      const N = G.N, n = N * N, e = effFor(p), water = p.mode === "water", ok = okFor(p);
      const dist = new Float64Array(n).fill(Infinity), done = new Uint8Array(n), pred = wantPred ? new Int32Array(n).fill(-1) : null;
      const h = heap();
      for (const [c, d] of near(src, ok)) if (d < dist[c]) { dist[c] = d; h.push(d, c); }
      const D = [[-1, -1], [-1, 0], [-1, 1], [0, -1], [0, 1], [1, -1], [1, 0], [1, 1]];
      while (h.size) {
        const u = h.pop(), du = h.k;
        if (done[u]) continue;
        done[u] = 1;
        const ur = (u / N) | 0, uc = u % N;
        for (const [dr, dc] of D) {
          const vr = ur + dr, vc = uc + dc;
          if (vr < 0 || vr >= N || vc < 0 || vc >= N) continue;
          const v = vr * N + vc;
          if (done[v] || !ok(v)) continue;
          const len = G.CELL * (dr && dc ? Math.SQRT2 : 1);
          let secs;
          if (water) secs = len;
          else {
            const dh = Math.abs(G.h[u] - G.h[v]);
            if (dh > len) continue;                                // more than one block up per block: a cliff or a wall
            secs = len / ((e[u] + e[v]) / 2) * (1 + G.SLOPE_COST * dh / len);
          }
          const nd = du + secs;
          if (nd < dist[v]) { dist[v] = nd; if (pred) pred[v] = u; h.push(nd, v); }
        }
      }
      return { dist, pred };
    }

    //Arrival at t: the best usable cell near it, plus the stretch to the counter. [seconds, cell]
    function arrive(r, t, ok) {
      let best = Infinity, cell = -1;
      for (const [c, d] of near(t, ok)) if (r.dist[c] + d < best) { best = r.dist[c] + d; cell = c; }
      return [best, cell];
    }

    function matrix(m) {
      const n = m.cells.length, ok = okFor(m.p), times = new Float64Array(n * n).fill(Infinity);
      for (let i = 0; i < n; i++) {
        const r = search(m.p, m.cells[i], false);
        for (let j = 0; j < n; j++) times[i * n + j] = i === j ? 0 : arrive(r, m.cells[j], ok)[0];
        if (i % 5 === 0) self.postMessage({ id: m.id, progress: i / n });
      }
      self.postMessage({ id: m.id, times }, [times.buffer]);
    }

    function row(m) {
      const r = search(m.p, m.start, false), ok = okFor(m.p);
      const times = Float64Array.from(m.cells, c => arrive(r, c, ok)[0]);
      self.postMessage({ id: m.id, times }, [times.buffer]);
    }

    function path(m) {
      const r = search(m.p, m.from, true), [seconds, end] = arrive(r, m.to, okFor(m.p));
      if (!isFinite(seconds)) return self.postMessage({ id: m.id, cells: null });
      const cells = [];
      for (let c = end; c !== -1; c = r.pred[c]) cells.push(c);
      cells.reverse();
      let road = 0;
      for (const c of cells) if (G.road[c] > 0 || G.paved[c]) road++;
      self.postMessage({ id: m.id, cells, onRoad: road / cells.length, seconds });
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
    const g = { N, CELL, SLOPE_COST, ROUGH_COST, OFFROAD_FOREST, OFFROAD_STEEP, STEEP_STEP, FREE_RADIUS,
      h: new Float32Array(n), road: new Float32Array(n), surf: new Float32Array(n), rough: new Float32Array(n),
      forest: new Uint8Array(n), paved: new Uint8Array(n), blocked: new Uint8Array(n), water: new Uint8Array(n),
      maxStep: new Uint8Array(n), cliff: new Uint8Array(n) };
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
      return r.cells ? { points: [a, ...r.cells.map(c => centerOf(c, size)), b], onRoad: r.onRoad, seconds: r.seconds } : null;
    },
  };
})();
