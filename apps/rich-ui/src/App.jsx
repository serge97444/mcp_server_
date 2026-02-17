import React, { useEffect, useMemo, useState } from "react";

function readHostData(currentHost) {
  const host = currentHost || window.openai || {};
  const toolOutput = host.toolOutput;
  if (toolOutput && typeof toolOutput === "object" && "data" in toolOutput) {
    return toolOutput.data || {};
  }
  return (
    toolOutput ||
    host.structuredContent ||
    host.widgetState ||
    window.__APP_DATA__ ||
    {}
  );
}

export default function App({ data, debug = false, host = null }) {
  const [liveHost, setLiveHost] = useState(host || window.openai || null);
  const [liveData, setLiveData] = useState(data || {});

  useEffect(() => {
    const handleUpdate = () => {
      const nextHost = window.openai || null;
      setLiveHost(nextHost);
      setLiveData(readHostData(nextHost));
    };

    handleUpdate();
    window.addEventListener("openai:set_globals", handleUpdate);
    return () => window.removeEventListener("openai:set_globals", handleUpdate);
  }, []);

  const {
    age = "-",
    versement_initial = "-",
    duree_investissment = "-",
    niveau_risque = "-",
    overall_gain = "-",
    conditions_generales = "",
  } = liveData || {};

  const isReady = useMemo(() => {
    const required = {
      age,
      versement_initial,
      duree_investissment,
      niveau_risque,
      overall_gain,
    };
    return Object.values(required).every((value) => {
      if (value === null || value === undefined) return false;
      if (typeof value !== "string") return true;
      const trimmed = value.trim();
      return trimmed !== "" && trimmed !== "-" && trimmed !== "—";
    });
  }, [age, versement_initial, duree_investissment, niveau_risque, overall_gain]);

  if (!isReady && !debug) {
    return (
      <div className="page">
        <section className="panel">
          <h2>Chargement...</h2>
          <p className="sub">Preparation de votre simulation.</p>
        </section>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="hero">
        <div>
          <p className="eyebrow">Amazing Life Insurance Company</p>
          <h1>Simulation PERI</h1>
          <p className="sub">
            Resume de profil et projection de gain. 
          </p>
        </div>
        <div className="badge">
          <div className="badge-label">Gain estime</div>
          <div className="badge-value">{overall_gain} EUR</div>
        </div>
      </header>

      <section className="panel">
        <h2>Profil client</h2>
        <div className="grid">
          <div className="card">
            <div className="label">Age</div>
            <div className="value">{age} ans</div>
          </div>
          <div className="card">
            <div className="label">Versement initial</div>
            <div className="value">{versement_initial} EUR</div>
          </div>
          <div className="card">
            <div className="label">Duree d'investissement</div>
            <div className="value">{duree_investissment} ans</div>
          </div>
          <div className="card">
            <div className="label">Niveau de risque</div>
            <div className="value">{niveau_risque} / 10</div>
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>Performance financiere</h2>
        <div className="highlight">
          <div className="highlight-title">Gain total estime</div>
          <div className="highlight-value">
            {overall_gain} EUR sur {duree_investissment} ans
          </div>
          <div className="highlight-note">
            Resultat indicatif, a valider avec votre conseiller.
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>Conditions generales</h2>
        <div className="conditions">{conditions_generales}</div>
      </section>

      {debug ? (
        <section className="panel">
          <h2>Debug (host)</h2>
          <pre className="debug">
            {JSON.stringify({ data: liveData, host: liveHost }, null, 2)}
          </pre>
        </section>
      ) : null}
    </div>
  );
}
