import { useMemo, useState } from "react";
import "./App.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:5000";
const INTEREST_OPTIONS = [
  "Undecided",
  "Play Next",
  "Interested",
  "Maybe",
  "Not Right Now",
  "Not Interested",
  "Completed",
];

function App() {
  const steamId = new URLSearchParams(window.location.search).get("steamid");

  const libraryKey = steamId ? `steamLibraryGames_${steamId}` : null;
  const libraryMetaKey = steamId ? `steamLibraryMeta_${steamId}` : null;

  const [games, setGames] = useState(() => {
    if (!libraryKey) return [];

    const saved = localStorage.getItem(libraryKey);
    return saved ? JSON.parse(saved) : [];
  });

  const [libraryMeta, setLibraryMeta] = useState(() => {
    if (!libraryMetaKey) return null;

    const saved = localStorage.getItem(libraryMetaKey);
    return saved ? JSON.parse(saved) : null;
  });

  const [hasFetchedLibrary, setHasFetchedLibrary] = useState(() => {
    if (!libraryKey) return false;
    return Boolean(localStorage.getItem(libraryKey));
  });

  const [isFetchingLibrary, setIsFetchingLibrary] = useState(false);
  const [fetchProgress, setFetchProgress] = useState(null);

  const [sourceFilter, setSourceFilter] = useState("All");
  const [statusFilter, setStatusFilter] = useState("All");
  const [interestFilter, setInterestFilter] = useState("All");
  const [sortBy, setSortBy] = useState("name");
  const [search, setSearch] = useState("");
  const [selectedGame, setSelectedGame] = useState(null);
  const [showCategories, setShowCategories] = useState(false);

  const [interestByGame, setInterestByGame] = useState(() => {
    const saved = localStorage.getItem("steamLibraryInterest");
    return saved ? JSON.parse(saved) : {};
  });

  const totalHours = games.reduce(
    (sum, game) => sum + (Number(game.playtimeHours) || 0),
    0
  );

  const playedCount = games.filter((game) => game.status === "Played").length;
  const backlogCount = games.filter((game) => game.status === "Backlog").length;

  const filteredGames = games
    .filter((game) => {
      const gameInterest = interestByGame[game.appid] || "Undecided";

      return (
        (sourceFilter === "All" || game.source === sourceFilter) &&
        (statusFilter === "All" || game.status === statusFilter) &&
        (interestFilter === "All" || gameInterest === interestFilter) &&
        game.name.toLowerCase().includes(search.toLowerCase())
      );
    })
    .sort((a, b) => {
      if (sortBy === "playtime") {
        return (b.playtimeHours || 0) - (a.playtimeHours || 0);
      }

      if (sortBy === "steamReviewPercent") {
        return (b.steamReviewPercent || 0) - (a.steamReviewPercent || 0);
      }

      if (sortBy === "metacritic") {
        return (Number(b.metacritic) || 0) - (Number(a.metacritic) || 0);
      }

      return a.name.localeCompare(b.name);
    });

  function signInWithSteam() {
    window.location.href = `${API_URL}/auth/steam`;
  }

  function fetchMyLibrary() {
    if (!steamId || isFetchingLibrary) return;

    setIsFetchingLibrary(true);
    setGames([]);
    setLibraryMeta(null);
    setHasFetchedLibrary(false);
    setSelectedGame(null);

    if (libraryKey) localStorage.removeItem(libraryKey);
    if (libraryMetaKey) localStorage.removeItem(libraryMetaKey);

    setFetchProgress({
      stage: "starting",
      message: "Starting Steam library scan...",
      percent: 0,
      processedGames: 0,
      totalGamesToProcess: 0,
      currentMember: null,
      currentGame: null,
      cachedGames: 0,
      newlyEnrichedGames: 0,
    });

    const streamUrl = `${API_URL}/api/library-enriched-stream?steamid=${steamId}`;
    const eventSource = new EventSource(streamUrl);

    eventSource.addEventListener("progress", (event) => {
      const progress = JSON.parse(event.data);

      setFetchProgress((current) => ({
        ...current,
        ...progress,
      }));
    });

    eventSource.addEventListener("complete", (event) => {
      const data = JSON.parse(event.data);
      const userGames = (data.games || []).sort((a, b) =>
        a.name.localeCompare(b.name)
      );

      const meta = {
        steamId,
        catalogVersion: data.catalogVersion || data.totalGames || "enriched",
        lastFetched: new Date().toISOString(),
        totalGames: data.totalGames || userGames.length,
        ownedGames: data.ownedGames || 0,
        familyGames: data.familyGames || 0,
        familyEnabled: Boolean(data.familyEnabled),
        familyName: data.familyName || null,
        familyMembers: data.members || data.familyMembers || [],
        failedFamilyMembers: (data.members || []).filter((member) => !member.loaded),
        cachedGames: data.cachedGames || 0,
        newlyEnrichedGames: data.newlyEnrichedGames || 0,
        hiddenGamesConfigured: data.hiddenGamesConfigured || 0,
        privateGamesFiltered: data.privateGamesFiltered || 0,
      };

      localStorage.setItem(libraryKey, JSON.stringify(userGames));
      localStorage.setItem(libraryMetaKey, JSON.stringify(meta));

      setGames(userGames);
      setLibraryMeta(meta);
      setHasFetchedLibrary(true);
      setSelectedGame(null);
      setFetchProgress({
        stage: "complete",
        message: `Done. Loaded ${userGames.length} unique games.`,
        percent: 100,
        processedGames: data.cachedGames + data.newlyEnrichedGames,
        totalGamesToProcess: data.cachedGames + data.newlyEnrichedGames,
        cachedGames: data.cachedGames || 0,
        newlyEnrichedGames: data.newlyEnrichedGames || 0,
      });
      setIsFetchingLibrary(false);
      eventSource.close();
    });

    eventSource.addEventListener("error", (event) => {
      console.error("Progress stream failed", event);
      setFetchProgress((current) => ({
        ...current,
        stage: "error",
        message:
          "The progress connection failed. Check the Flask console for the exact error.",
      }));
      setIsFetchingLibrary(false);
      eventSource.close();
    });
  }

  function updateInterest(appid, value) {
    setInterestByGame((current) => {
      const updated = { ...current, [appid]: value };
      localStorage.setItem("steamLibraryInterest", JSON.stringify(updated));
      return updated;
    });
  }

  function closeDrawer() {
    setSelectedGame(null);
    setShowCategories(false);
  }

  function getInterestLabel(value) {
    const labels = {
      Undecided: "Undecided",
      "Play Next": "🔥 Play Next",
      Interested: "👍 Interested",
      Maybe: "🤔 Maybe",
      "Not Right Now": "😴 Not Right Now",
      "Not Interested": "❌ Not Interested",
      Completed: "🏆 Completed",
    };

    return labels[value] || value;
  }

  function exportInterestList() {
    const exportedGames = games
      .map((game) => ({
        appid: game.appid,
        name: game.name,
        interest: interestByGame[game.appid] || "Undecided",
        status: game.status,
        playtime: game.playtime,
        genres: game.genres || [],
        steamReviewPercent: game.steamReviewPercent,
        metacritic: game.metacritic,
        releaseDate: game.releaseDate,
        source: game.source,
        owner: game.owner,
        ownerSteamId: game.ownerSteamId,
        familyOwners: game.familyOwners || [],
        storeUrl: game.storeUrl,
      }))
      .filter((game) => game.interest !== "Undecided");

    const blob = new Blob([JSON.stringify(exportedGames, null, 2)], {
      type: "application/json",
    });

    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");

    link.href = url;
    link.download = "steam-interest-list.json";
    link.click();

    URL.revokeObjectURL(url);
  }

  function parseHours(value) {
    if (value === null || value === undefined) return null;

    if (typeof value === "number") return value;

    const match = String(value).match(/[\d.]+/);
    return match ? Number(match[0]) : null;
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function buildPreferenceProfile() {
    const genreWeights = {};
    const categoryWeights = {};

    games.forEach((game) => {
      const interest = interestByGame[game.appid] || "Undecided";
      const playtimeHours = Number(game.playtimeHours) || 0;

      let weight = 0;

      if (interest === "Play Next") weight += 8;
      if (interest === "Interested") weight += 5;
      if (interest === "Maybe") weight += 2;
      if (interest === "Completed") weight += 4;
      if (interest === "Not Right Now") weight -= 1;
      if (interest === "Not Interested") weight -= 8;

      if (playtimeHours >= 50) weight += 5;
      else if (playtimeHours >= 20) weight += 3;
      else if (playtimeHours >= 5) weight += 1;

      (game.genres || []).forEach((genre) => {
        genreWeights[genre] = (genreWeights[genre] || 0) + weight;
      });

      (game.categories || []).forEach((category) => {
        categoryWeights[category] = (categoryWeights[category] || 0) + weight * 0.35;
      });
    });

    return { genreWeights, categoryWeights };
  }

  function getRecommendationScore(game, profile) {
    const interest = interestByGame[game.appid] || "Undecided";
    const metacritic = Number(game.metacritic) || 0;
    const steamReviewPercent = Number(game.steamReviewPercent) || 0;
    const steamReviewTotal = Number(game.steamReviewTotal) || 0;
    const playtimeHours = Number(game.playtimeHours) || 0;
    const avgBeatHours = parseHours(game.avgBeat);

    if (interest === "Not Interested" || interest === "Completed") return -999;

    let score = 0;
    const reasons = [];

    if (interest === "Play Next") {
      score += 45;
      reasons.push("you marked it as Play Next");
    } else if (interest === "Interested") {
      score += 30;
      reasons.push("you marked it as Interested");
    } else if (interest === "Maybe") {
      score += 15;
      reasons.push("you marked it as Maybe");
    }

    if (game.status === "Backlog") {
      score += 18;
      reasons.push("it is still in your backlog");
    } else if (playtimeHours > 0 && playtimeHours < 2) {
      score += 8;
      reasons.push("you barely started it");
    } else if (playtimeHours >= 20) {
      score -= 18;
    }

    const genreMatch = (game.genres || []).reduce((sum, genre) => {
      return sum + Math.max(0, profile.genreWeights[genre] || 0);
    }, 0);

    const categoryMatch = (game.categories || []).reduce((sum, category) => {
      return sum + Math.max(0, profile.categoryWeights[category] || 0);
    }, 0);

    const preferenceScore = clamp(genreMatch + categoryMatch, 0, 35);

    if (preferenceScore >= 20) reasons.push("it matches genres you tend to like");
    else if (preferenceScore >= 8) reasons.push("it partially matches your taste");

    score += preferenceScore;

    if (steamReviewPercent >= 95 && steamReviewTotal >= 1000) {
      score += 18;
      reasons.push("Steam reviews are excellent");
    } else if (steamReviewPercent >= 90) {
      score += 14;
      reasons.push("Steam reviews are very strong");
    } else if (steamReviewPercent >= 80) {
      score += 9;
    } else if (steamReviewPercent > 0 && steamReviewPercent < 65) {
      score -= 10;
    }

    if (metacritic >= 90) {
      score += 14;
      reasons.push("Metacritic is excellent");
    } else if (metacritic >= 80) {
      score += 9;
    } else if (metacritic > 0 && metacritic < 65) {
      score -= 8;
    }

    if (avgBeatHours !== null) {
      if (avgBeatHours <= 6) {
        score += 10;
        reasons.push("it is short enough to finish soon");
      } else if (avgBeatHours <= 15) {
        score += 6;
      } else if (avgBeatHours >= 60) {
        score -= 8;
        reasons.push("it is a long commitment");
      }
    }

    return {
      score: Math.round(score),
      reasons: reasons.slice(0, 3),
    };
  }

  function recommendGame() {
    const profile = buildPreferenceProfile();

    const candidates = games
      .map((game) => {
        const recommendation = getRecommendationScore(game, profile);

        return {
          ...game,
          recommendationScore: recommendation.score,
          recommendationReasons: recommendation.reasons,
        };
      })
      .filter((game) => game.recommendationScore > 0)
      .sort((a, b) => b.recommendationScore - a.recommendationScore);

    if (candidates.length === 0) {
      alert("Mark some games as 🔥 Play Next, 👍 Interested, 🤔 Maybe, or play a few games first.");
      return;
    }

    const topCandidates = candidates.slice(0, 8);
    const totalWeight = topCandidates.reduce(
      (sum, game) => sum + game.recommendationScore,
      0
    );

    let roll = Math.random() * totalWeight;
    let selected = topCandidates[0];

    for (const game of topCandidates) {
      roll -= game.recommendationScore;

      if (roll <= 0) {
        selected = game;
        break;
      }
    }

    setSelectedGame(selected);
    setShowCategories(false);
  }

  if (!steamId) {
    return (
      <main className="page">
        <header className="hero">
          <h1>My Steam Library</h1>
          <p>Sign in with Steam to load your own library.</p>
        </header>

        <section className="login-panel">
          <h2>Connect your Steam account</h2>
          <p>
            Your games will be loaded from Steam and matched with genres,
            reviews, ratings, and time-to-beat data when available.
          </p>

          <button className="steam-login-button" onClick={signInWithSteam}>
            Sign in with Steam
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="page">
      <header className="hero">
        <h1>My Steam Library</h1>
        <p>Owned games, Steam Family games, ratings, genres and time to beat.</p>
      </header>

      <section className="login-panel">
        <p>
          Logged in with Steam ID: <strong>{steamId}</strong>
        </p>

        {libraryMeta?.lastFetched && (
          <p>
            Last fetched:{" "}
            <strong>
              {new Date(libraryMeta.lastFetched).toLocaleString()}
            </strong>
          </p>
        )}

        {libraryMeta && (
          <p>
            Cached: <strong>{libraryMeta.cachedGames || 0}</strong> | Newly
            enriched: <strong>{libraryMeta.newlyEnrichedGames || 0}</strong>
          </p>
        )}

        {libraryMeta?.familyEnabled && (
          <p>
            Family enabled: <strong>{libraryMeta.familyName}</strong> | Owned: {" "}
            <strong>{libraryMeta.ownedGames || 0}</strong> | Shared: {" "}
            <strong>{libraryMeta.familyGames || 0}</strong>
          </p>
        )}

        {libraryMeta?.privateGamesFiltered > 0 && (
          <p>
            Private games hidden from public family view: {" "}
            <strong>{libraryMeta.privateGamesFiltered}</strong>
          </p>
        )}

        {libraryMeta?.failedFamilyMembers?.length > 0 && (
          <p>
            Could not load {libraryMeta.failedFamilyMembers.length} family member(s).
            They may have private libraries.
          </p>
        )}

        <button
          className="steam-login-button"
          onClick={fetchMyLibrary}
          disabled={isFetchingLibrary}
        >
          {isFetchingLibrary
            ? "Fetching Steam Family..."
            : hasFetchedLibrary
              ? "Refresh Library"
              : "Fetch My Library"}
        </button>

        {fetchProgress && (
          <div
            style={{
              marginTop: "1rem",
              padding: "1rem",
              borderRadius: "16px",
              background: "rgba(255, 255, 255, 0.06)",
              border: "1px solid rgba(255, 255, 255, 0.12)",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: "1rem",
                marginBottom: "0.65rem",
              }}
            >
              <strong>
                {fetchProgress.stage === "complete"
                  ? "Library ready"
                  : fetchProgress.stage === "error"
                    ? "Something failed"
                    : "Loading library"}
              </strong>
              <strong>{fetchProgress.percent || 0}%</strong>
            </div>

            <div
              style={{
                width: "100%",
                height: "12px",
                borderRadius: "999px",
                overflow: "hidden",
                background: "rgba(255, 255, 255, 0.12)",
              }}
            >
              <div
                style={{
                  width: `${fetchProgress.percent || 0}%`,
                  height: "100%",
                  borderRadius: "999px",
                  background: "linear-gradient(90deg, #66c0f4, #a2d2ff)",
                  transition: "width 0.25s ease",
                }}
              />
            </div>

            <p style={{ marginTop: "0.75rem", marginBottom: 0 }}>
              {fetchProgress.message}
            </p>

            {(fetchProgress.currentMember || fetchProgress.currentGame) && (
              <p style={{ marginTop: "0.35rem", marginBottom: 0, opacity: 0.8 }}>
                {fetchProgress.currentMember && (
                  <>
                    Member: <strong>{fetchProgress.currentMember}</strong>
                  </>
                )}
                {fetchProgress.currentGame && (
                  <>
                    {fetchProgress.currentMember ? " · " : ""}
                    Game: <strong>{fetchProgress.currentGame}</strong>
                  </>
                )}
              </p>
            )}

            {fetchProgress.totalGamesToProcess > 0 && (
              <p style={{ marginTop: "0.35rem", marginBottom: 0, opacity: 0.8 }}>
                Processed {fetchProgress.processedGames || 0} of{" "}
                {fetchProgress.totalGamesToProcess} entries · Cache hits:{" "}
                {fetchProgress.cachedGames || 0} · Newly enriched:{" "}
                {fetchProgress.newlyEnrichedGames || 0}
              </p>
            )}
          </div>
        )}
      </section>

      {!hasFetchedLibrary && (
        <section className="login-panel">
          <h2>No library loaded yet</h2>
          <p>Click Fetch My Library to load your Steam games.</p>
        </section>
      )}

      {hasFetchedLibrary && (
        <>
          <section className="summary">
            <div>
              <strong>{games.length}</strong>
              <span>Total Games</span>
            </div>
            {libraryMeta?.familyEnabled && (
              <div>
                <strong>{libraryMeta.familyGames || 0}</strong>
                <span>Family Shared</span>
              </div>
            )}
            <div>
              <strong>{playedCount}</strong>
              <span>Played</span>
            </div>
            <div>
              <strong>{backlogCount}</strong>
              <span>Backlog</span>
            </div>
            <div>
              <strong>{totalHours.toFixed(1)}h</strong>
              <span>Total Hours</span>
            </div>
          </section>

          <section className="toolbar">
            <input
              className="search"
              type="text"
              placeholder="Search games..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />

            <div className="controls">
              <select
                value={sourceFilter}
                onChange={(e) => setSourceFilter(e.target.value)}
              >
                <option value="All">All Sources</option>
                <option value="Owned">Owned</option>
                <option value="Steam Family">Steam Family</option>
              </select>

              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                <option value="All">All Status</option>
                <option value="Backlog">Backlog</option>
                <option value="Played">Played</option>
              </select>

              <select
                value={interestFilter}
                onChange={(e) => setInterestFilter(e.target.value)}
              >
                <option value="All">All Interests</option>
                {INTEREST_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {getInterestLabel(option)}
                  </option>
                ))}
              </select>

              <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                <option value="name">Sort by Name</option>
                <option value="playtime">Sort by Playtime</option>
                <option value="steamReviewPercent">Sort by Steam Reviews</option>
                <option value="metacritic">Sort by Metacritic</option>
              </select>

              <button className="export-button" onClick={exportInterestList}>
                📥 Export List
              </button>

              <button className="recommend-button" onClick={recommendGame}>
                🎲 Recommend Something
              </button>
            </div>

            <p className="counter">
              Showing {filteredGames.length} of {games.length} games
            </p>
          </section>

          <section className="grid">
            {filteredGames.map((game) => {
              const gameInterest = interestByGame[game.appid] || "Undecided";

              return (
                <article
                  className="card"
                  key={game.appid}
                  onClick={() => setSelectedGame(game)}
                >
                  <img
                    className="game-image"
                    src={game.image}
                    alt={game.name}
                    loading="lazy"
                    onError={(e) => {
                      e.currentTarget.style.display = "none";
                    }}
                  />

                  <div className="content">
                    <div className="card-top">
                      <h2>{game.name}</h2>
                      <span>{game.status}</span>
                    </div>

                    <p>{game.type}</p>

                    <div className="stats">
                      <span>{getInterestLabel(gameInterest)}</span>
                      <span>Beat: {game.avgBeat}</span>
                      <span>Played: {game.playtime}</span>
                      <span>{game.source}</span>
                      {game.owner && <span>Owner: {game.owner}</span>}
                    </div>
                  </div>
                </article>
              );
            })}
          </section>
        </>
      )}

      {selectedGame && (
        <>
          <div className="backdrop" onClick={closeDrawer} />

          <aside className="drawer">
            <button className="close-button" onClick={closeDrawer}>
              ×
            </button>

            <img
              className="drawer-image"
              src={selectedGame.image}
              alt={selectedGame.name}
            />

            <h2>{selectedGame.name}</h2>

            {selectedGame.recommendationScore !== undefined && (
              <p className="recommendation-score">
                🎯 Recommended Match: {selectedGame.recommendationScore} pts
              </p>
            )}

            {selectedGame.recommendationReasons?.length > 0 && (
              <ul className="recommendation-reasons">
                {selectedGame.recommendationReasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            )}

            <label className="field">
              Interest
              <select
                value={interestByGame[selectedGame.appid] || "Undecided"}
                onChange={(e) =>
                  updateInterest(selectedGame.appid, e.target.value)
                }
              >
                {INTEREST_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {getInterestLabel(option)}
                  </option>
                ))}
              </select>
            </label>

            <div className="detail-list">
              <p>
                <strong>Status:</strong> {selectedGame.status}
              </p>
              <p>
                <strong>Source:</strong> {selectedGame.source || "Owned"}
              </p>
              <p>
                <strong>Owner:</strong> {selectedGame.owner || "Me"}
              </p>
              <p>
                <strong>Played:</strong> {selectedGame.playtime}
              </p>
              <p>
                <strong>Genres:</strong>{" "}
                {selectedGame.genres?.join(", ") || "Unknown"}
              </p>
              <p>
                <strong>Steam Reviews:</strong>{" "}
                {selectedGame.steamReviewPercent
                  ? `${selectedGame.steamReviewPercent}% (${selectedGame.steamReviewTotal || 0} reviews)`
                  : "Unknown"}
              </p>
              <p>
                <strong>Metacritic:</strong>{" "}
                {selectedGame.metacritic || "Unknown"}
              </p>
              <p>
                <strong>Release date:</strong>{" "}
                {selectedGame.releaseDate || "Unknown"}
              </p>
              <p>
                <strong>HowLongToBeat:</strong>{" "}
                {selectedGame.avgBeat || "Unknown"}
              </p>

              {selectedGame.familyOwners?.length > 1 && (
                <p>
                  <strong>Available from:</strong>{" "}
                  {selectedGame.familyOwners.map((owner) => owner.name).join(", ")}
                </p>
              )}

              <button
                className="toggle-button"
                onClick={() => setShowCategories((value) => !value)}
              >
                {showCategories
                  ? "Hide categories"
                  : `Show categories (${selectedGame.categories?.length || 0})`}
              </button>

              {showCategories && (
                <p className="categories-text">
                  {selectedGame.categories?.join(", ") || "Unknown"}
                </p>
              )}
            </div>

            <a
              className="steam-link"
              href={selectedGame.storeUrl}
              target="_blank"
              rel="noreferrer"
            >
              🛒 View on Steam
            </a>
          </aside>
        </>
      )}
    </main>
  );
}

export default App;