/**
 * @file bgp-minimal-example.cc
 * @brief Minimal BGP example: 3 ASes with transit through AS 65001
 *
 * Demonstrates BGP routing where AS 65001 receives routes from AS 65000
 * and announces them to AS 65002 over a main and a redundant link.
 *
 * Shows:
 *      - network creation
 *      - IP addressing
 *      - BGP speaker setup with eBGP peering
 *      - route propagation over 100 seconds
 *
 * Network flow: 10.0.0.0/25 -> ... -> 10.0.2.0/24
 */

#include "ns3/core-module.h"
#include "ns3/internet-apps-module.h"
#include "ns3/v4ping.h"
#include "bgp-minimal-scenario.h"

using namespace ns3;

#define NS_SIM_LEN Seconds (3600)
#define LINK_SWITCHOVER_TIME Seconds (45)
#define LINK_SWITCHOVER_BACK_TIME Seconds (3000)
#define LINK_FAIL_TIME Seconds (60)
#define LINK_REPAIR_TIME Seconds (1500)
#define RNG_SEED 12345
#define RNG_RUN 1

NS_LOG_COMPONENT_DEFINE ("BgpMinimal");

namespace
{
uint32_t g_rxTotal = 0;
uint32_t g_rxTransitionWindow = 0;
uint32_t g_rxMainDownWindow = 0;

void
OnPingRtt (ns3::Time /*rtt*/)
{
    const ns3::Time now = ns3::Simulator::Now ();
    ++g_rxTotal;
    if ((now >= LINK_SWITCHOVER_TIME) && (now < LINK_FAIL_TIME))
    {
        ++g_rxTransitionWindow;
    }
    if ((now >= LINK_FAIL_TIME) && (now < LINK_REPAIR_TIME))
    {
        ++g_rxMainDownWindow;
    }
}

uint32_t
ExpectedPingReplies (ns3::Time windowStart, ns3::Time windowEnd)
{
    uint32_t expected = 0;
    for (ns3::Time t = ns3::Seconds (10); t < NS_SIM_LEN; t += ns3::Seconds (1))
    {
        if ((t >= windowStart) && (t < windowEnd))
        {
            ++expected;
        }
    }
    return expected;
}
} // namespace

int main (int argc, char *argv[])
{
    bool enableProactiveSwitchover = true;
    double switchoverTimeSeconds = 45.0;
    double switchoverBackTimeSeconds = 3000.0;
    CommandLine cmd;
    cmd.AddValue ("enableProactiveSwitchover",
                  "Enable scheduled system switchover events",
                  enableProactiveSwitchover);
    cmd.AddValue ("switchoverTimeSeconds",
                  "Time to switch d12_main -> d12_red",
                  switchoverTimeSeconds);
    cmd.AddValue ("switchoverBackTimeSeconds",
                  "Time to switch d12_red -> d12_main",
                  switchoverBackTimeSeconds);
    cmd.Parse (argc, argv);

    const Time switchoverTime = Seconds (switchoverTimeSeconds);
    const Time switchoverBackTime = Seconds (switchoverBackTimeSeconds);

    // Deterministic simulation settings for repeatable failover experiments.
    RngSeedManager::SetSeed (RNG_SEED);
    RngSeedManager::SetRun (RNG_RUN);

    NS_LOG_INFO ("Setup & Logging");
    LogComponentEnable ("BgpMinimal", LOG_LEVEL_INFO);
    //LogComponentEnable("BgpLog", LOG_LEVEL_INFO); // libbgp
    LogComponentEnable ("Bgp", LOG_LEVEL_INFO); // session

    BgpMinimalScenario scenario;
    NS_LOG_INFO ("Create nodes for AS routers and internal hosts");
    NS_LOG_INFO ("Create CSMA links (IXP and LANs)");
    scenario.BuildTopology ();
    scenario.ConfigureAddressing ();
    scenario.ConfigureRouting ();
    scenario.ConfigureBgp (NS_SIM_LEN);

    V4PingHelper ping (scenario.GetPingDestinationAddress ());
    ping.SetAttribute("Verbose", BooleanValue (true));
    ApplicationContainer ping_apps = ping.Install (scenario.GetPingSourceNode ());
    ping_apps.Start (Seconds (10));
    ping_apps.Stop (NS_SIM_LEN);
    Ptr<V4Ping> ping_app = DynamicCast<V4Ping> (ping_apps.Get (0));
    NS_ABORT_MSG_IF (ping_app == nullptr, "Failed to access V4Ping application instance");
    ping_app->TraceConnectWithoutContext ("Rtt", MakeCallback (&OnPingRtt));

    if (enableProactiveSwitchover)
    {
        scenario.SetSwitchoverWindow (switchoverTime,
                                      switchoverTime,
                                      LINK_FAIL_TIME);
        NS_ABORT_MSG_IF (!scenario.HasValidSwitchoverWindow (),
                         "Invalid switchover window: expected intent <= activation < failure");
        scenario.ScheduleLinkChange (BgpMinimalScenario::LinkId::MAIN,
                                     BgpMinimalScenario::LinkId::REDUNDANT,
                                     switchoverTime);
        scenario.ScheduleLinkChange (BgpMinimalScenario::LinkId::REDUNDANT,
                                     BgpMinimalScenario::LinkId::MAIN,
                                     switchoverBackTime);
    }

    // Schedule link failure and repair
    scenario.ScheduleEvents (LINK_FAIL_TIME, LINK_REPAIR_TIME);

    NS_LOG_INFO ("Running simulation...");
    Simulator::Run();

    const uint32_t expectedTotal = ExpectedPingReplies (Seconds (10), NS_SIM_LEN);
    const uint32_t expectedTransition = ExpectedPingReplies (LINK_SWITCHOVER_TIME, LINK_FAIL_TIME);
    const uint32_t expectedMainDown = ExpectedPingReplies (LINK_FAIL_TIME, LINK_REPAIR_TIME);
    NS_LOG_UNCOND ("[ICMP][SUMMARY] total_rx=" << g_rxTotal
                  << " total_expected=" << expectedTotal
                  << " total_lost=" << (expectedTotal - g_rxTotal));
    NS_LOG_UNCOND ("[ICMP][SUMMARY] transition_rx=" << g_rxTransitionWindow
                  << " transition_expected=" << expectedTransition
                  << " transition_lost=" << (expectedTransition - g_rxTransitionWindow));
    NS_LOG_UNCOND ("[ICMP][SUMMARY] main_down_rx=" << g_rxMainDownWindow
                  << " main_down_expected=" << expectedMainDown
                  << " main_down_lost=" << (expectedMainDown - g_rxMainDownWindow));

    NS_LOG_INFO ("Simulation ended. Cleaning up...");
    Simulator::Destroy();
    return 0;
}
