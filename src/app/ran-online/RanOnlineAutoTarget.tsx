"use client";

import { useState, useEffect, useRef, useCallback } from "react";

type Mob = {
  id: number;
  name: string;
  x: number;
  y: number;
  hp: number;
  maxHp: number;
  level: number;
  type: "normal" | "elite" | "boss";
  moving: boolean;
  dx: number;
  dy: number;
};

const MOB_NAMES = [
  "Hooligan",
  "Hooligan",
  "Hooligan",
  "Hooligan",
  "Street Fighter",
  "Gangster",
  "Thug",
  "Enforcer",
];

const MOB_TYPES: ("normal" | "elite" | "boss")[] = [
  "normal",
  "normal",
  "normal",
  "normal",
  "normal",
  "elite",
  "normal",
  "boss",
];

function generateMobs(count: number, width: number, height: number): Mob[] {
  return Array.from({ length: count }, (_, i) => ({
    id: i,
    name: MOB_NAMES[i % MOB_NAMES.length],
    x: 80 + Math.random() * (width - 160),
    y: 80 + Math.random() * (height - 160),
    hp: 100,
    maxHp: 100,
    level: 20 + Math.floor(Math.random() * 15),
    type: MOB_TYPES[i % MOB_TYPES.length],
    moving: true,
    dx: (Math.random() - 0.5) * 0.6,
    dy: (Math.random() - 0.5) * 0.6,
  }));
}

const TYPE_COLOR: Record<string, string> = {
  normal: "#ffffff",
  elite: "#ffcc00",
  boss: "#ff4444",
};

const TYPE_LABEL: Record<string, string> = {
  normal: "",
  elite: " [Elite]",
  boss: " [BOSS]",
};

export default function RanOnlineAutoTarget() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef<{
    mobs: Mob[];
    targetId: number | null;
    autoTarget: boolean;
    attackTimer: number;
    playerX: number;
    playerY: number;
    floatingTexts: { x: number; y: number; text: string; alpha: number; id: number }[];
    nextFloatId: number;
  }>({
    mobs: [],
    targetId: null,
    autoTarget: false,
    attackTimer: 0,
    playerX: 0,
    playerY: 0,
    floatingTexts: [],
    nextFloatId: 0,
  });

  const [uiState, setUiState] = useState({
    targetId: null as number | null,
    autoTarget: false,
    mobCount: 0,
    killCount: 0,
  });

  const killCountRef = useRef(0);
  const rafRef = useRef<number>(0);
  const lastTimeRef = useRef(0);

  const getCanvas = () => canvasRef.current;

  const spawnMob = useCallback((canvas: HTMLCanvasElement) => {
    const s = stateRef.current;
    const id = Date.now() + Math.random();
    const idx = Math.floor(Math.random() * MOB_NAMES.length);
    s.mobs.push({
      id,
      name: MOB_NAMES[idx],
      x: 80 + Math.random() * (canvas.width - 160),
      y: 80 + Math.random() * (canvas.height - 160),
      hp: 100,
      maxHp: 100,
      level: 20 + Math.floor(Math.random() * 15),
      type: MOB_TYPES[idx],
      moving: true,
      dx: (Math.random() - 0.5) * 0.6,
      dy: (Math.random() - 0.5) * 0.6,
    });
  }, []);

  // Init
  useEffect(() => {
    const canvas = getCanvas();
    if (!canvas) return;
    const s = stateRef.current;
    s.playerX = canvas.width / 2;
    s.playerY = canvas.height / 2;
    s.mobs = generateMobs(8, canvas.width, canvas.height);
    setUiState((u) => ({ ...u, mobCount: s.mobs.length }));
  }, []);

  // Game loop
  useEffect(() => {
    const canvas = getCanvas();
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const ATTACK_INTERVAL = 1200; // ms between attacks
    const ATTACK_RANGE = 120;
    const MOB_SPEED = 0.4;
    const MOB_RADIUS = 18;
    const PLAYER_RADIUS = 16;

    function findNearestMob(): Mob | null {
      const s = stateRef.current;
      let nearest: Mob | null = null;
      let minDist = Infinity;
      for (const mob of s.mobs) {
        const dx = mob.x - s.playerX;
        const dy = mob.y - s.playerY;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < minDist) {
          minDist = dist;
          nearest = mob;
        }
      }
      return nearest;
    }

    function loop(now: number) {
      const dt = Math.min(now - (lastTimeRef.current || now), 50);
      lastTimeRef.current = now;
      const s = stateRef.current;

      // Move mobs
      for (const mob of s.mobs) {
        if (!mob.moving) continue;
        mob.x += mob.dx * dt * MOB_SPEED;
        mob.y += mob.dy * dt * MOB_SPEED;
        if (mob.x < 40 || mob.x > canvas.width - 40) mob.dx *= -1;
        if (mob.y < 40 || mob.y > canvas.height - 40) mob.dy *= -1;
        mob.x = Math.max(40, Math.min(canvas.width - 40, mob.x));
        mob.y = Math.max(40, Math.min(canvas.height - 40, mob.y));
      }

      // Auto target logic
      if (s.autoTarget) {
        if (s.targetId === null || !s.mobs.find((m) => m.id === s.targetId)) {
          const nearest = findNearestMob();
          if (nearest) {
            s.targetId = nearest.id;
            setUiState((u) => ({ ...u, targetId: nearest.id }));
          }
        }

        // Move player toward target
        const target = s.mobs.find((m) => m.id === s.targetId);
        if (target) {
          const dx = target.x - s.playerX;
          const dy = target.y - s.playerY;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist > ATTACK_RANGE * 0.7) {
            s.playerX += (dx / dist) * dt * 0.8;
            s.playerY += (dy / dist) * dt * 0.8;
          }

          // Attack
          s.attackTimer += dt;
          if (s.attackTimer >= ATTACK_INTERVAL && dist < ATTACK_RANGE) {
            s.attackTimer = 0;
            const dmg = 15 + Math.floor(Math.random() * 25);
            target.hp = Math.max(0, target.hp - dmg);

            // Floating damage text
            s.floatingTexts.push({
              x: target.x + (Math.random() - 0.5) * 20,
              y: target.y - MOB_RADIUS - 10,
              text: `-${dmg}`,
              alpha: 1,
              id: s.nextFloatId++,
            });

            if (target.hp <= 0) {
              s.mobs = s.mobs.filter((m) => m.id !== target.id);
              s.targetId = null;
              killCountRef.current += 1;
              setUiState((u) => ({
                ...u,
                targetId: null,
                killCount: killCountRef.current,
                mobCount: s.mobs.length,
              }));
              // Respawn after delay
              setTimeout(() => {
                spawnMob(canvas);
                setUiState((u) => ({ ...u, mobCount: stateRef.current.mobs.length }));
              }, 3000);
            } else {
              setUiState((u) => ({ ...u, mobCount: s.mobs.length }));
            }
          }
        }
      }

      // Float texts
      s.floatingTexts = s.floatingTexts
        .map((f) => ({ ...f, y: f.y - dt * 0.05, alpha: f.alpha - dt * 0.0015 }))
        .filter((f) => f.alpha > 0);

      // Draw
      draw(ctx, canvas, s);

      rafRef.current = requestAnimationFrame(loop);
    }

    rafRef.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafRef.current);
  }, [spawnMob]);

  function draw(
    ctx: CanvasRenderingContext2D,
    canvas: HTMLCanvasElement,
    s: typeof stateRef.current
  ) {
    // Background - isometric floor tiles
    ctx.fillStyle = "#2a2a2a";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Draw tile grid
    const tileW = 80;
    const tileH = 40;
    ctx.strokeStyle = "rgba(255,255,255,0.04)";
    ctx.lineWidth = 1;
    for (let row = -2; row < canvas.height / tileH + 4; row++) {
      for (let col = -2; col < canvas.width / tileW + 4; col++) {
        const x = col * tileW + (row % 2) * (tileW / 2);
        const y = row * tileH;
        ctx.beginPath();
        ctx.moveTo(x, y + tileH / 2);
        ctx.lineTo(x + tileW / 2, y);
        ctx.lineTo(x + tileW, y + tileH / 2);
        ctx.lineTo(x + tileW / 2, y + tileH);
        ctx.closePath();
        ctx.stroke();
      }
    }

    const target = s.mobs.find((m) => m.id === s.targetId);

    // Draw mobs
    for (const mob of s.mobs) {
      const isTargeted = mob.id === s.targetId;
      const r = mob.type === "boss" ? 24 : mob.type === "elite" ? 20 : MOB_RADIUS;

      // Shadow
      ctx.save();
      ctx.globalAlpha = 0.3;
      ctx.fillStyle = "#000";
      ctx.beginPath();
      ctx.ellipse(mob.x, mob.y + r, r * 0.8, r * 0.25, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      // Target reticle (spinning)
      if (isTargeted) {
        const time = Date.now() / 1000;
        ctx.save();
        ctx.strokeStyle = "#ffcc00";
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 4]);
        ctx.lineDashOffset = -time * 20;
        ctx.globalAlpha = 0.9;
        ctx.beginPath();
        ctx.arc(mob.x, mob.y, r + 12, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);

        // Corner brackets
        ctx.globalAlpha = 1;
        ctx.strokeStyle = "#ffdd00";
        ctx.lineWidth = 2.5;
        const bs = r + 16;
        const bl = 10;
        // top-left
        ctx.beginPath(); ctx.moveTo(mob.x - bs, mob.y - bs + bl); ctx.lineTo(mob.x - bs, mob.y - bs); ctx.lineTo(mob.x - bs + bl, mob.y - bs); ctx.stroke();
        // top-right
        ctx.beginPath(); ctx.moveTo(mob.x + bs - bl, mob.y - bs); ctx.lineTo(mob.x + bs, mob.y - bs); ctx.lineTo(mob.x + bs, mob.y - bs + bl); ctx.stroke();
        // bottom-left
        ctx.beginPath(); ctx.moveTo(mob.x - bs, mob.y + bs - bl); ctx.lineTo(mob.x - bs, mob.y + bs); ctx.lineTo(mob.x - bs + bl, mob.y + bs); ctx.stroke();
        // bottom-right
        ctx.beginPath(); ctx.moveTo(mob.x + bs - bl, mob.y + bs); ctx.lineTo(mob.x + bs, mob.y + bs); ctx.lineTo(mob.x + bs, mob.y + bs - bl); ctx.stroke();
        ctx.restore();
      }

      // Mob body
      const grad = ctx.createRadialGradient(mob.x - r * 0.3, mob.y - r * 0.3, 1, mob.x, mob.y, r);
      if (mob.type === "boss") {
        grad.addColorStop(0, "#ff6666");
        grad.addColorStop(1, "#880000");
      } else if (mob.type === "elite") {
        grad.addColorStop(0, "#ffee88");
        grad.addColorStop(1, "#886600");
      } else {
        grad.addColorStop(0, "#6688cc");
        grad.addColorStop(1, "#223366");
      }
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(mob.x, mob.y, r, 0, Math.PI * 2);
      ctx.fill();

      // Mob outline
      ctx.strokeStyle = isTargeted ? "#ffdd00" : "rgba(255,255,255,0.2)";
      ctx.lineWidth = isTargeted ? 2 : 1;
      ctx.beginPath();
      ctx.arc(mob.x, mob.y, r, 0, Math.PI * 2);
      ctx.stroke();

      // Mob name tag
      const nameColor = TYPE_COLOR[mob.type];
      ctx.save();
      ctx.font = "bold 11px 'Courier New', monospace";
      ctx.textAlign = "center";
      const label = mob.name + TYPE_LABEL[mob.type];
      const tw = ctx.measureText(label).width;
      ctx.fillStyle = "rgba(0,0,0,0.6)";
      ctx.fillRect(mob.x - tw / 2 - 4, mob.y - r - 24, tw + 8, 16);
      ctx.fillStyle = nameColor;
      ctx.fillText(label, mob.x, mob.y - r - 11);
      // Level
      ctx.font = "10px 'Courier New', monospace";
      ctx.fillStyle = "#aaaaaa";
      ctx.fillText(`Lv.${mob.level}`, mob.x, mob.y - r - 28);
      ctx.restore();

      // HP bar
      const hpW = r * 2.2;
      ctx.fillStyle = "#330000";
      ctx.fillRect(mob.x - hpW / 2, mob.y + r + 5, hpW, 5);
      const hpFill = (mob.hp / mob.maxHp) * hpW;
      const hpColor = mob.hp > 60 ? "#22cc22" : mob.hp > 30 ? "#cccc22" : "#cc2222";
      ctx.fillStyle = hpColor;
      ctx.fillRect(mob.x - hpW / 2, mob.y + r + 5, hpFill, 5);
      ctx.strokeStyle = "rgba(255,255,255,0.2)";
      ctx.lineWidth = 0.5;
      ctx.strokeRect(mob.x - hpW / 2, mob.y + r + 5, hpW, 5);
    }

    // Attack line
    if (s.autoTarget && target) {
      const dist = Math.sqrt(
        (target.x - s.playerX) ** 2 + (target.y - s.playerY) ** 2
      );
      if (dist < 130) {
        const time = Date.now() / 200;
        ctx.save();
        ctx.globalAlpha = 0.4 + 0.2 * Math.sin(time);
        ctx.strokeStyle = "#ffdd44";
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 6]);
        ctx.beginPath();
        ctx.moveTo(s.playerX, s.playerY);
        ctx.lineTo(target.x, target.y);
        ctx.stroke();
        ctx.restore();
      }
    }

    // Player character
    const px = s.playerX;
    const py = s.playerY;

    // Player shadow
    ctx.save();
    ctx.globalAlpha = 0.35;
    ctx.fillStyle = "#000";
    ctx.beginPath();
    ctx.ellipse(px, py + PLAYER_RADIUS, PLAYER_RADIUS * 0.8, PLAYER_RADIUS * 0.25, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    // Player body
    const pGrad = ctx.createRadialGradient(px - 5, py - 5, 1, px, py, PLAYER_RADIUS);
    pGrad.addColorStop(0, "#ffffff");
    pGrad.addColorStop(0.4, "#aaddff");
    pGrad.addColorStop(1, "#2244aa");
    ctx.fillStyle = pGrad;
    ctx.beginPath();
    ctx.arc(px, py, PLAYER_RADIUS, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#88ccff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(px, py, PLAYER_RADIUS, 0, Math.PI * 2);
    ctx.stroke();

    // Player aura
    const time2 = Date.now() / 1000;
    ctx.save();
    ctx.globalAlpha = 0.15 + 0.08 * Math.sin(time2 * 3);
    ctx.strokeStyle = "#88ccff";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(px, py, PLAYER_RADIUS + 6 + 2 * Math.sin(time2 * 2), 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();

    // Player name
    ctx.save();
    ctx.font = "bold 11px 'Courier New', monospace";
    ctx.textAlign = "center";
    ctx.fillStyle = "rgba(0,0,0,0.6)";
    ctx.fillRect(px - 45, py - PLAYER_RADIUS - 22, 90, 16);
    ctx.fillStyle = "#88ddff";
    ctx.fillText("HayleyXGrimmie", px, py - PLAYER_RADIUS - 9);
    ctx.restore();

    // Floating damage texts
    for (const ft of s.floatingTexts) {
      ctx.save();
      ctx.globalAlpha = ft.alpha;
      ctx.font = "bold 14px 'Courier New', monospace";
      ctx.textAlign = "center";
      ctx.fillStyle = "#ff4444";
      ctx.strokeStyle = "#000";
      ctx.lineWidth = 3;
      ctx.strokeText(ft.text, ft.x, ft.y);
      ctx.fillText(ft.text, ft.x, ft.y);
      ctx.restore();
    }
  }

  const toggleAutoTarget = () => {
    const s = stateRef.current;
    s.autoTarget = !s.autoTarget;
    if (!s.autoTarget) {
      s.targetId = null;
      s.attackTimer = 0;
      setUiState((u) => ({ ...u, autoTarget: false, targetId: null }));
    } else {
      setUiState((u) => ({ ...u, autoTarget: true }));
    }
  };

  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    const s = stateRef.current;

    for (const mob of s.mobs) {
      const dx = mob.x - cx;
      const dy = mob.y - cy;
      if (Math.sqrt(dx * dx + dy * dy) < 28) {
        s.targetId = mob.id;
        setUiState((u) => ({ ...u, targetId: mob.id }));
        return;
      }
    }
    // Click empty = deselect
    s.targetId = null;
    setUiState((u) => ({ ...u, targetId: null }));
  };

  const targetedMob = stateRef.current.mobs.find((m) => m.id === uiState.targetId);

  return (
    <div
      style={{
        background: "#0a0a14",
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "flex-start",
        fontFamily: "'Courier New', monospace",
        color: "#ccc",
        padding: "16px",
      }}
    >
      {/* Title bar */}
      <div
        style={{
          width: "100%",
          maxWidth: 900,
          background: "linear-gradient(90deg, #0d1a3a, #1a0d2e)",
          border: "1px solid #334",
          borderBottom: "2px solid #4466aa",
          padding: "8px 16px",
          marginBottom: 12,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: uiState.autoTarget ? "#22ff44" : "#444",
              boxShadow: uiState.autoTarget ? "0 0 8px #22ff44" : "none",
              transition: "all 0.3s",
            }}
          />
          <span style={{ color: "#88aaff", fontWeight: "bold", fontSize: 14 }}>
            RAN ONLINE — Auto Target System
          </span>
        </div>
        <div style={{ fontSize: 11, color: "#556" }}>
          Mobs: {uiState.mobCount} &nbsp;|&nbsp; Kills: {uiState.killCount}
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, width: "100%", maxWidth: 900 }}>
        {/* Game canvas */}
        <canvas
          ref={canvasRef}
          width={620}
          height={460}
          onClick={handleCanvasClick}
          style={{
            border: "1px solid #334",
            cursor: "crosshair",
            display: "block",
            flexShrink: 0,
          }}
        />

        {/* Side panel */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 10 }}>
          {/* Auto Target button */}
          <button
            onClick={toggleAutoTarget}
            style={{
              background: uiState.autoTarget
                ? "linear-gradient(180deg, #1a4a1a, #0d2b0d)"
                : "linear-gradient(180deg, #1a1a3a, #0d0d1e)",
              border: `2px solid ${uiState.autoTarget ? "#22cc44" : "#334466"}`,
              color: uiState.autoTarget ? "#44ff66" : "#8899bb",
              padding: "12px 0",
              fontSize: 13,
              fontFamily: "'Courier New', monospace",
              fontWeight: "bold",
              cursor: "pointer",
              letterSpacing: 1,
              boxShadow: uiState.autoTarget ? "0 0 12px rgba(34,204,68,0.3)" : "none",
              transition: "all 0.2s",
            }}
          >
            {uiState.autoTarget ? "◉ AUTO TARGET ON" : "○ AUTO TARGET OFF"}
          </button>

          {/* Target info box */}
          <div
            style={{
              background: "linear-gradient(180deg, #0d1220, #080d18)",
              border: `1px solid ${targetedMob ? "#4466aa" : "#222"}`,
              padding: 12,
              flex: 1,
            }}
          >
            <div
              style={{
                fontSize: 10,
                color: "#4466aa",
                borderBottom: "1px solid #223",
                paddingBottom: 6,
                marginBottom: 10,
                letterSpacing: 2,
              }}
            >
              TARGET INFO
            </div>

            {targetedMob ? (
              <>
                <div style={{ marginBottom: 6 }}>
                  <span style={{ color: "#556", fontSize: 10 }}>Name: </span>
                  <span
                    style={{
                      color: TYPE_COLOR[targetedMob.type],
                      fontWeight: "bold",
                      fontSize: 13,
                    }}
                  >
                    {targetedMob.name}
                    {TYPE_LABEL[targetedMob.type]}
                  </span>
                </div>

                <div style={{ marginBottom: 6 }}>
                  <span style={{ color: "#556", fontSize: 10 }}>Level: </span>
                  <span style={{ color: "#aabbcc", fontSize: 12 }}>
                    {targetedMob.level}
                  </span>
                </div>

                <div style={{ marginBottom: 4 }}>
                  <span style={{ color: "#556", fontSize: 10 }}>Type: </span>
                  <span
                    style={{
                      color: TYPE_COLOR[targetedMob.type],
                      fontSize: 11,
                      textTransform: "uppercase",
                    }}
                  >
                    {targetedMob.type}
                  </span>
                </div>

                {/* HP bar */}
                <div style={{ marginTop: 10 }}>
                  <div
                    style={{
                      fontSize: 10,
                      color: "#556",
                      display: "flex",
                      justifyContent: "space-between",
                      marginBottom: 4,
                    }}
                  >
                    <span>HP</span>
                    <span style={{ color: "#aabbcc" }}>
                      {targetedMob.hp} / {targetedMob.maxHp}
                    </span>
                  </div>
                  <div
                    style={{
                      height: 10,
                      background: "#1a0000",
                      border: "1px solid #330000",
                      position: "relative",
                    }}
                  >
                    <div
                      style={{
                        position: "absolute",
                        top: 0,
                        left: 0,
                        height: "100%",
                        width: `${(targetedMob.hp / targetedMob.maxHp) * 100}%`,
                        background:
                          targetedMob.hp > 60
                            ? "#22aa22"
                            : targetedMob.hp > 30
                            ? "#aaaa22"
                            : "#aa2222",
                        transition: "width 0.1s, background 0.3s",
                      }}
                    />
                  </div>
                </div>

                {uiState.autoTarget && (
                  <div
                    style={{
                      marginTop: 12,
                      padding: "6px 8px",
                      background: "rgba(34,204,68,0.08)",
                      border: "1px solid rgba(34,204,68,0.2)",
                      fontSize: 10,
                      color: "#22cc44",
                      letterSpacing: 1,
                    }}
                  >
                    ◉ ATTACKING TARGET
                  </div>
                )}
              </>
            ) : (
              <div style={{ color: "#334", fontSize: 11, marginTop: 8 }}>
                {uiState.autoTarget
                  ? "Searching for target..."
                  : "No target selected"}
              </div>
            )}
          </div>

          {/* Instructions */}
          <div
            style={{
              background: "#080d14",
              border: "1px solid #1a2030",
              padding: 10,
              fontSize: 10,
              color: "#445",
              lineHeight: 1.8,
            }}
          >
            <div style={{ color: "#334466", marginBottom: 4, letterSpacing: 1 }}>
              CONTROLS
            </div>
            <div>• Click mob to manually target</div>
            <div>• Toggle Auto Target to hunt</div>
            <div>• Auto moves & attacks nearest</div>
            <div>• Mobs respawn after 3s</div>
            <div style={{ marginTop: 6, color: "#ffcc00" }}>
              ■ Elite &nbsp; <span style={{ color: "#ff4444" }}>■ Boss</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
