import { ArrowRight, Crosshair, Layers3, Radar } from "lucide-react";
import Link from "next/link";

const featureCards = [
  {
    title: "Tasaci\u00f3n Inteligente",
    description: "Comparables reales y confianza.",
    icon: Crosshair,
  },
  {
    title: "An\u00e1lisis de Publicaciones",
    description: "Informaci\u00f3n estructurada.",
    icon: Layers3,
  },
  {
    title: "Radar de Oportunidades",
    description: "Detecta oportunidades antes que otros.",
    icon: Radar,
  },
];

function TerritoryVisual() {
  const nodes = [
    [86, 182],
    [150, 150],
    [218, 196],
    [302, 130],
    [394, 168],
    [482, 104],
    [576, 158],
    [682, 112],
    [774, 172],
    [894, 130],
    [1016, 190],
    [196, 242],
    [348, 252],
    [530, 220],
    [718, 240],
    [878, 224],
  ];

  return (
    <section className="public-territory" aria-label="Visual territorial Valoria">
      <div className="public-territory-orbit" />
      <svg className="public-territory-map" aria-hidden="true" viewBox="0 0 1120 340">
        <defs>
          <radialGradient id="territoryGlow" cx="50%" cy="43%" r="58%">
            <stop offset="0%" stopColor="rgba(190, 167, 255, 0.34)" />
            <stop offset="44%" stopColor="rgba(124, 92, 255, 0.14)" />
            <stop offset="100%" stopColor="rgba(2, 3, 10, 0)" />
          </radialGradient>
          <linearGradient id="mapStroke" x1="0%" x2="100%" y1="0%" y2="0%">
            <stop offset="0%" stopColor="rgba(221, 214, 254, 0.18)" />
            <stop offset="46%" stopColor="rgba(221, 214, 254, 0.82)" />
            <stop offset="100%" stopColor="rgba(168, 85, 247, 0.22)" />
          </linearGradient>
          <filter id="softNodeGlow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <ellipse cx="560" cy="210" rx="610" ry="142" fill="url(#territoryGlow)" />
        <path
          d="M44 202 L134 156 L230 178 L318 116 L430 146 L520 92 L632 138 L724 98 L846 156 L1016 126 L1092 184 L996 242 L832 216 L704 268 L552 232 L390 286 L234 240 Z"
          fill="rgba(124, 92, 255, 0.045)"
          stroke="url(#mapStroke)"
          strokeWidth="1.15"
        />
        <g fill="none" stroke="rgba(196, 181, 253, 0.25)" strokeWidth="0.9">
          <path d="M134 156 L318 116 L520 92 L724 98 L1016 126" />
          <path d="M230 178 L430 146 L632 138 L846 156 L1092 184" />
          <path d="M44 202 L234 240 L390 286 L552 232 L704 268 L832 216 L996 242" />
          <path d="M318 116 L390 286 M520 92 L552 232 M724 98 L704 268 M430 146 L704 268 M230 178 L632 138 M846 156 L832 216" />
        </g>
        <g fill="none" stroke="rgba(221, 214, 254, 0.16)" strokeWidth="0.8">
          <ellipse cx="560" cy="206" rx="70" ry="21" />
          <ellipse cx="560" cy="206" rx="116" ry="35" />
          <ellipse cx="560" cy="206" rx="166" ry="49" />
        </g>
        <g filter="url(#softNodeGlow)">
          {nodes.map(([cx, cy]) => (
            <circle cx={cx} cy={cy} fill="#ede9fe" key={`${cx}-${cy}`} r="3" />
          ))}
          <circle cx="560" cy="206" fill="#ffffff" r="4.5" />
        </g>
        <g stroke="rgba(196, 181, 253, 0.24)" strokeWidth="0.8">
          <path d="M150 150 V78 M482 104 V38 M682 112 V58 M894 130 V76" />
          <circle cx="150" cy="78" fill="#ddd6fe" r="2" />
          <circle cx="482" cy="38" fill="#ddd6fe" r="2" />
          <circle cx="682" cy="58" fill="#ddd6fe" r="2" />
          <circle cx="894" cy="76" fill="#ddd6fe" r="2" />
        </g>
      </svg>

      <span className="public-territory-label public-label-coords">
        33.4489 S
        <br />
        70.6693 O
      </span>
      <span className="public-territory-label public-label-zone">
        Microzona
        <br />
        Delta 500 m
      </span>
      <span className="public-territory-label public-label-data">
        Datos
        <br />
        En tiempo real
      </span>
      <div className="public-territory-pin">V</div>
    </section>
  );
}

export default function LandingPage() {
  return (
    <main className="public-landing-page">
      <style>{`
        .public-landing-page {
          width: 100%;
          min-height: 100vh;
          overflow-x: hidden;
          background:
            radial-gradient(circle at 50% 14%, rgba(124, 92, 255, 0.12), transparent 25rem),
            radial-gradient(circle at 50% 100%, rgba(124, 92, 255, 0.22), transparent 36rem),
            linear-gradient(180deg, #02030a 0%, #050511 52%, #02030a 100%);
          color: #ffffff;
          font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }

        .public-landing-shell {
          position: relative;
          z-index: 1;
          display: flex;
          width: 100%;
          min-height: 100vh;
          flex-direction: column;
          align-items: center;
          padding: clamp(30px, 4.8vh, 44px) 0 28px;
        }

        .public-hero {
          width: min(100% - 40px, 1040px);
          text-align: center;
        }

        .public-logo {
          display: inline-block;
          color: #ffffff;
          font-size: clamp(1.45rem, 2.6vw, 2.15rem);
          font-weight: 300;
          letter-spacing: clamp(0.36em, 1.05vw, 0.58em);
          line-height: 1;
          text-decoration: none;
          text-transform: uppercase;
          text-shadow: 0 0 26px rgba(255, 255, 255, 0.18);
        }

        .public-badge {
          display: inline-flex;
          margin-top: clamp(30px, 4.1vh, 42px);
          border: 1px solid rgba(139, 92, 246, 0.78);
          border-radius: 999px;
          background: rgba(9, 7, 18, 0.62);
          padding: 7px 18px;
          color: #ede9fe;
          box-shadow: 0 0 24px rgba(124, 92, 255, 0.18);
          font-size: 0.68rem;
          font-weight: 650;
          letter-spacing: 0.18em;
          line-height: 1;
          text-transform: uppercase;
        }

        .public-headline {
          max-width: 880px;
          margin: clamp(18px, 2.6vh, 24px) auto 0;
          color: #f8fafc;
          font-size: clamp(3.05rem, 5.55vw, 5.25rem);
          font-weight: 300;
          letter-spacing: 0;
          line-height: 1.04;
          text-wrap: balance;
        }

        .public-headline span {
          display: block;
        }

        .public-headline strong {
          color: #925cff;
          font-weight: 300;
          text-shadow: 0 0 30px rgba(124, 92, 255, 0.44);
        }

        .public-subtitle {
          max-width: 650px;
          margin: clamp(18px, 2.5vh, 24px) auto 0;
          color: rgba(226, 232, 240, 0.82);
          font-size: clamp(1rem, 1.35vw, 1.16rem);
          font-weight: 300;
          line-height: 1.58;
        }

        .public-actions {
          display: flex;
          flex-wrap: wrap;
          justify-content: center;
          gap: 16px;
          margin-top: clamp(22px, 3.1vh, 30px);
        }

        .public-button {
          display: inline-flex;
          min-width: 188px;
          min-height: 52px;
          align-items: center;
          justify-content: center;
          gap: 13px;
          border-radius: 999px;
          padding: 0 30px;
          color: #ffffff;
          font-size: 0.98rem;
          font-weight: 620;
          line-height: 1;
          text-decoration: none;
          transition: border-color 160ms ease, background 160ms ease, box-shadow 160ms ease, transform 160ms ease;
        }

        .public-button:hover {
          transform: translateY(-1px);
        }

        .public-button.public-primary {
          border: 1px solid rgba(167, 139, 250, 0.78);
          background: linear-gradient(135deg, #a56cff 0%, #6d28d9 100%);
          box-shadow: 0 0 34px rgba(124, 92, 255, 0.34);
        }

        .public-button.public-secondary {
          border: 1px solid rgba(148, 163, 184, 0.36);
          background: rgba(4, 5, 14, 0.46);
          box-shadow: inset 0 0 24px rgba(124, 92, 255, 0.04);
        }

        .public-button.public-secondary:hover {
          border-color: rgba(167, 139, 250, 0.7);
          background: rgba(124, 92, 255, 0.1);
        }

        .public-territory {
          position: relative;
          width: 100vw;
          height: clamp(230px, 26vw, 322px);
          margin-top: clamp(22px, 3.3vh, 34px);
          overflow: hidden;
          isolation: isolate;
        }

        .public-territory::before {
          position: absolute;
          inset: 0;
          z-index: 1;
          background:
            linear-gradient(90deg, #02030a 0%, rgba(2, 3, 10, 0) 16%, rgba(2, 3, 10, 0) 84%, #02030a 100%),
            linear-gradient(180deg, rgba(2, 3, 10, 0.18), rgba(2, 3, 10, 0) 42%, rgba(2, 3, 10, 0.74) 100%);
          content: "";
          pointer-events: none;
        }

        .public-territory-orbit {
          position: absolute;
          left: 50%;
          bottom: -72%;
          width: min(1380px, 124vw);
          height: 112%;
          transform: translateX(-50%);
          border: 1px solid rgba(196, 181, 253, 0.2);
          border-radius: 50%;
          background:
            radial-gradient(circle at 50% 0%, rgba(124, 92, 255, 0.26), rgba(19, 12, 42, 0.18) 38%, rgba(2, 3, 10, 0) 70%),
            repeating-radial-gradient(ellipse at 50% 0%, rgba(196, 181, 253, 0.11) 0 1px, transparent 1px 18px);
          box-shadow: 0 -34px 130px rgba(124, 92, 255, 0.28);
        }

        .public-territory-map {
          position: absolute;
          left: 50%;
          bottom: 0;
          z-index: 2;
          width: min(1220px, 112vw);
          height: 100%;
          transform: translateX(-50%);
          filter: drop-shadow(0 0 22px rgba(124, 92, 255, 0.34));
          overflow: visible;
        }

        .public-territory-pin {
          position: absolute;
          left: 50%;
          top: 53%;
          z-index: 4;
          color: #ffffff;
          font-size: clamp(4rem, 6.1vw, 6.2rem);
          font-weight: 300;
          line-height: 1;
          text-shadow:
            0 0 18px rgba(255, 255, 255, 0.9),
            0 0 54px rgba(124, 92, 255, 0.95);
          transform: translate(-50%, -50%);
        }

        .public-territory-pin::after {
          position: absolute;
          left: 50%;
          top: 52%;
          z-index: -1;
          width: clamp(88px, 8vw, 122px);
          height: clamp(88px, 8vw, 122px);
          transform: translate(-50%, -50%);
          border-radius: 999px;
          background: radial-gradient(circle, rgba(124, 92, 255, 0.5), rgba(124, 92, 255, 0.08) 54%, transparent 72%);
          content: "";
        }

        .public-territory-label {
          position: absolute;
          z-index: 5;
          color: rgba(148, 163, 184, 0.72);
          font-size: 0.62rem;
          letter-spacing: 0.14em;
          line-height: 1.55;
          text-transform: uppercase;
        }

        .public-label-coords {
          left: max(24px, calc(50vw - 440px));
          top: 12%;
        }

        .public-label-zone {
          right: max(24px, calc(50vw - 430px));
          top: 19%;
        }

        .public-label-data {
          right: max(24px, calc(50vw - 520px));
          bottom: 19%;
        }

        .public-features {
          display: grid;
          width: min(100% - 40px, 960px);
          grid-template-columns: repeat(3, minmax(0, 1fr));
          margin: clamp(8px, 1.7vh, 18px) auto 0;
          text-align: center;
        }

        .public-feature {
          padding: 0 clamp(18px, 3vw, 38px);
        }

        .public-feature + .public-feature {
          border-left: 1px solid rgba(255, 255, 255, 0.12);
        }

        .public-feature-icon {
          display: grid;
          width: 56px;
          height: 56px;
          place-items: center;
          margin: 0 auto;
          border: 1px solid rgba(196, 181, 253, 0.52);
          border-radius: 999px;
          background: radial-gradient(circle, rgba(124, 92, 255, 0.22), rgba(2, 3, 10, 0.14));
          color: #ddd6fe;
          box-shadow: 0 0 26px rgba(124, 92, 255, 0.2);
        }

        .public-feature h2 {
          max-width: 230px;
          margin: 16px auto 0;
          color: #f8fafc;
          font-size: clamp(1.18rem, 1.75vw, 1.55rem);
          font-weight: 300;
          line-height: 1.18;
        }

        .public-feature p {
          max-width: 240px;
          margin: 10px auto 0;
          color: rgba(203, 213, 225, 0.68);
          font-size: 0.9rem;
          line-height: 1.45;
        }

        .public-footer-note {
          margin-top: clamp(26px, 3.5vh, 42px);
          color: rgba(203, 213, 225, 0.66);
          font-size: 0.68rem;
          letter-spacing: clamp(0.22em, 0.8vw, 0.42em);
          line-height: 1.4;
          text-align: center;
          text-transform: uppercase;
        }

        @media (max-width: 920px) {
          .public-headline {
            font-size: clamp(2.8rem, 9.8vw, 4.7rem);
          }

          .public-territory {
            height: clamp(240px, 38vw, 310px);
          }

          .public-territory-map {
            width: 1120px;
            max-width: none;
          }

          .public-territory-label {
            display: none;
          }
        }

        @media (max-width: 700px) {
          .public-landing-shell {
            padding: 28px 0 26px;
          }

          .public-hero {
            width: min(100% - 32px, 520px);
          }

          .public-logo {
            font-size: 1.45rem;
            letter-spacing: 0.34em;
          }

          .public-badge {
            margin-top: 30px;
          }

          .public-headline {
            font-size: clamp(2.55rem, 12vw, 3.7rem);
            line-height: 1.05;
          }

          .public-subtitle {
            max-width: 410px;
            line-height: 1.5;
          }

          .public-actions {
            align-items: stretch;
            flex-direction: column;
            gap: 12px;
          }

          .public-button {
            width: 100%;
            min-width: 0;
          }

          .public-territory {
            height: 268px;
            margin-top: 24px;
          }

          .public-territory-map {
            width: 980px;
          }

          .public-territory-pin {
            font-size: 4.2rem;
          }

          .public-features {
            width: min(100% - 32px, 420px);
            grid-template-columns: 1fr;
            gap: 28px;
            margin-top: 18px;
            padding: 28px 0 0;
            border-top: 1px solid rgba(255, 255, 255, 0.1);
          }

          .public-feature {
            padding: 0;
          }

          .public-feature + .public-feature {
            border-left: 0;
          }
        }
      `}</style>

      <div className="public-landing-shell">
        <section className="public-hero" aria-labelledby="landing-title">
          <Link className="public-logo" href="/">
            Valoria
          </Link>

          <div className="public-badge">Beta Privada</div>

          <h1 className="public-headline" id="landing-title">
            <span>La nueva forma</span>
            <span>de entender el</span>
            <strong>mercado inmobiliario.</strong>
          </h1>

          <p className="public-subtitle">
            Tasa propiedades, analiza publicaciones y descubre oportunidades con inteligencia
            inmobiliaria.
          </p>

          <div className="public-actions">
            <Link className="public-button public-primary" href="/login">
              Entrar
              <ArrowRight aria-hidden="true" size={17} strokeWidth={1.8} />
            </Link>
            <Link className="public-button public-secondary" href="https://valoria-beta.netlify.app/register">
              Solicitar acceso
            </Link>
          </div>
        </section>

        <TerritoryVisual />

        <section className="public-features" aria-label="Capacidades principales">
          {featureCards.map((feature) => {
            const Icon = feature.icon;
            return (
              <article className="public-feature" key={feature.title}>
                <div className="public-feature-icon">
                  <Icon aria-hidden="true" size={25} strokeWidth={1.35} />
                </div>
                <h2>{feature.title}</h2>
                <p>{feature.description}</p>
              </article>
            );
          })}
        </section>

        <footer className="public-footer-note">Acceso exclusivo para invitados</footer>
      </div>
    </main>
  );
}
