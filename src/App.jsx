import { useMemo, useState } from "react";
import staticGames from "./data/games.json";
import "./App.css";

const API_URL = "https://steam-library-dashboard.onrender.com";
const CATALOG_VERSION = `${staticGames.length}-${
  staticGames.map((game) => game.catalogUpdatedAt || "").sort().at(-1) || "catalog"
}`;

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

  const catalogByAppId = useMemo(() => {
    return Object.fromEntries(staticGames.map((game) => [game.appid, game]));
  }, []);

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

      return a.name.localeCompare(b.name);
    });

  function signInWithSteam() {
    window.location.href = `${API_URL}/auth/steam`;
  }

  async function fetchMyLibrary() {
    if (!steamId) return;

    setIsFetchingLibrary(true);

    try {
      const response = await fetch(
        `${API_URL}/api/owned-games?steamid=${steamId}`
      );

      if (!response.ok) {
        throw new Error("Could not fetch Steam library");
      }

      const data = await response.json();
      const steamGames = data?.response?.games || [];

      const userGames = steamGames
        .map((steamGame) => {
          const catalogGame = catalogByAppId[steamGame.appid] || {};
          const playtimeHours = Math.round(
            ((steamGame.playtime_forever || 0) / 60) * 10
          ) / 10;

          return {
            ...catalogGame,
            appid: steamGame.appid,
            name: steamGame.name || catalogGame.name || "Unknown",
            source: "Owned",
            owner: "Me",
            playtime: `${playtimeHours}h`,
            playtimeHours,
            status: playtimeHours === 0 ? "Backlog" : "Played",
            type: catalogGame.type || "Unknown",
            genres: catalogGame.genres || [],
            categories: catalogGame.categories || [],
            rating:
              catalogGame.rating || catalogGame.steamReviewSummary || "Unknown",
            steamReviewSummary: catalogGame.steamReviewSummary || "Unknown",
            steamReviewPercent: catalogGame.steamReviewPercent || null,
            steamReviewTotal: catalogGame.steamReviewTotal || null,
            metacritic: catalogGame.metacritic || "Unknown",
            avgBeat: catalogGame.avgBeat || "Unknown",
            releaseDate: catalogGame.releaseDate || "Unknown",
            storeUrl:
              catalogGame.storeUrl ||
              `https://store.steampowered.com/app/${steamGame.appid}`,
            image:
              catalogGame.image ||
              `https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/${steamGame.appid}/header.jpg`,
          };
        })
        .sort((a, b) => a.name.localeCompare(b.name));

      const meta = {
        steamId,
        catalogVersion: CATALOG_VERSION,
        lastFetched: new Date().toISOString(),
        totalGames: userGames.length,
      };

      localStorage.setItem(libraryKey, JSON.stringify(userGames));
      localStorage.setItem(libraryMetaKey, JSON.stringify(meta));

      setGames(userGames);
      setLibraryMeta(meta);
      setHasFetchedLibrary(true);
      setSelectedGame(null);
    } catch (error) {
      console.error(error);
      alert("Could not fetch your Steam library. Your game details may be private.");
    } finally {
      setIsFetchingLibrary(false);
    }
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

  function getRecommendationScore(game) {
    const interest = interestByGame[game.appid] || "Undecided";
    const metacritic = Number(game.metacritic) || 0;
    const steamReviewPercent = Number(game.steamReviewPercent) || 0;
    const playtimeHours = Number(game.playtimeHours) || 0;

    if (interest === "Not Interested" || interest === "Completed") return -999;

    let score = 0;

    if (interest === "Play Next") score += 50;
    if (interest === "Interested") score += 30;
    if (interest === "Maybe") score += 10;
    if (game.status === "Backlog") score += 15;

    if (steamReviewPercent >= 90) score += 15;
    else if (steamReviewPercent >= 80) score += 10;
    else if (steamReviewPercent >= 70) score += 5;

    if (metacritic >= 85) score += 10;
    else if (metacritic >= 75) score += 5;

    if (playtimeHours > 20) score -= 20;

    return score;
  }

  function recommendGame() {
    const candidates = games
      .map((game) => ({
        ...game,
        recommendationScore: getRecommendationScore(game),
      }))
      .filter((game) => game.recommendationScore > 0)
      .sort((a, b) => b.recommendationScore - a.recommendationScore);

    if (candidates.length === 0) {
      alert("Mark some games as 🔥 Play Next, 👍 Interested, or 🤔 Maybe first.");
      return;
    }

    const topCandidates = candidates.slice(0, 10);
    const randomGame =
      topCandidates[Math.floor(Math.random() * topCandidates.length)];

    setSelectedGame(randomGame);
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
        <p>Owned games, ratings, genres and time to beat.</p>
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

        <button
          className="steam-login-button"
          onClick={fetchMyLibrary}
          disabled={isFetchingLibrary}
        >
          {isFetchingLibrary
            ? "Fetching..."
            : hasFetchedLibrary
              ? "Refresh Library"
              : "Fetch My Library"}
        </button>
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
              <span>Games</span>
            </div>
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