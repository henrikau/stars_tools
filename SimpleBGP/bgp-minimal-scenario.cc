#include "bgp-minimal-scenario.h"
#include "ns3/core-module.h"
#include "ns3/csma-module.h"
#include "ns3/internet-module.h"
#include "ns3/bgp.h"
#include "ns3helper-network.h"
#include <sstream>

namespace
{
const char*
LinkIdToString (BgpMinimalScenario::LinkId link)
{
  return (link == BgpMinimalScenario::LinkId::MAIN) ? "d12_main" : "d12_red";
}

const char*
StageToString (BgpMinimalState::EventStage stage)
{
  switch (stage)
    {
    case BgpMinimalState::EventStage::INIT:
      return "INIT";
    case BgpMinimalState::EventStage::SWITCHOVER_SCHEDULED:
      return "SWITCHOVER_SCHEDULED";
    case BgpMinimalState::EventStage::SWITCHED_TO_RED:
      return "SWITCHED_TO_RED";
    case BgpMinimalState::EventStage::PHYSICAL_MAIN_DOWN:
      return "PHYSICAL_MAIN_DOWN";
    case BgpMinimalState::EventStage::PHYSICAL_MAIN_UP:
      return "PHYSICAL_MAIN_UP";
    case BgpMinimalState::EventStage::SWITCHED_BACK_TO_MAIN:
      return "SWITCHED_BACK_TO_MAIN";
    }
  return "UNKNOWN_STAGE";
}

void
LogScenarioEvent (const char* domain, const std::string& detail)
{
  std::ostringstream oss;
  oss << "[EVENT][" << domain << "][t=" << ns3::Simulator::Now ().GetSeconds ()
      << "s] " << detail;
  NS_LOG_UNCOND (oss.str ());
}
} // namespace

BgpMinimalScenario::BgpMinimalScenario ()
  : m_mainPhysicalUp (true),
    m_redPhysicalUp (true),
    m_activeLink (LinkId::MAIN),
    m_hasValidSwitchoverWindow (false),
    m_switchoverIntentTime (ns3::Seconds (0)),
    m_switchoverActivationTime (ns3::Seconds (0)),
    m_switchoverHardDeadline (ns3::Seconds (0))
{
}

void BgpMinimalScenario::BuildTopology ()
{
  m_state.nodes.Create (6);

  ns3::InternetStackHelper internet;
  internet.Install (m_state.nodes);

  ns3::CsmaHelper csma_routers;
  ns3::CsmaHelper csma_lan;

  // Inter-domain links
  csma_routers.SetChannelAttribute ("DataRate", ns3::StringValue ("10Gbps"));
  csma_routers.SetChannelAttribute ("Delay", ns3::StringValue ("100us"));

  // Intra-domain (internal) links
  csma_lan.SetChannelAttribute("DataRate", ns3::StringValue ("1Gbps"));
  csma_lan.SetChannelAttribute("Delay", ns3::StringValue ("100us"));

  // Inter-domain links
  m_state.d01      = csma_routers.Install(ns3::NodeContainer (m_state.nodes.Get(0), m_state.nodes.Get(1)));
  m_state.d12_main = csma_routers.Install(ns3::NodeContainer (m_state.nodes.Get(1), m_state.nodes.Get(2)));
  m_state.d12_red  = csma_routers.Install(ns3::NodeContainer (m_state.nodes.Get(1), m_state.nodes.Get(2)));

  // LANs
  m_state.d0lan = csma_lan.Install(ns3::NodeContainer (m_state.nodes.Get (0), m_state.nodes.Get (3)));
  m_state.d1lan = csma_lan.Install(ns3::NodeContainer (m_state.nodes.Get (1), m_state.nodes.Get (4)));
  m_state.d2lan = csma_lan.Install(ns3::NodeContainer (m_state.nodes.Get (2), m_state.nodes.Get (5)));
}

void BgpMinimalScenario::ConfigureAddressing ()
{
  m_state.if01      = ns3helper::AssignP2p31(m_state.d01,      ns3::Ipv4Address ("10.250.0.2"), ns3::Ipv4Address ("10.250.0.3"));
  m_state.if12_main = ns3helper::AssignP2p31(m_state.d12_main, ns3::Ipv4Address ("10.250.0.4"), ns3::Ipv4Address ("10.250.0.5"));
  m_state.if12_red  = ns3helper::AssignP2p31(m_state.d12_red,  ns3::Ipv4Address ("10.250.0.6"), ns3::Ipv4Address ("10.250.0.7"));

  // Assign LAN addresses
  ns3::Ipv4AddressHelper ipv4;
  ipv4.SetBase ("10.0.0.0", "255.255.255.0"); m_state.if0lan = ipv4.Assign (m_state.d0lan);
  ipv4.SetBase ("10.0.1.0", "255.255.255.0"); m_state.if1lan = ipv4.Assign (m_state.d1lan);
  ipv4.SetBase ("10.0.2.0", "255.255.255.0"); m_state.if2lan = ipv4.Assign (m_state.d2lan);

  // Keep both links physically available from start so red can stay warm.
  // Main remains the planned primary path until system switchover event.
  ns3helper::bringUpLink (m_state.nodes, m_state.if12_main, 1u, 2u);
  ns3helper::bringUpLink (m_state.nodes, m_state.if12_red, 1u, 2u);
}

void BgpMinimalScenario::ConfigureRouting ()
{
  m_state.host0_ipv4 = m_state.nodes.Get (3)->GetObject<ns3::Ipv4> ();
  m_state.host1_ipv4 = m_state.nodes.Get (4)->GetObject<ns3::Ipv4> ();
  m_state.host2_ipv4 = m_state.nodes.Get (5)->GetObject<ns3::Ipv4> ();

  ns3helper::SetHostDefaultRoute(m_state.host0_ipv4, m_state.if0lan.GetAddress (1), m_state.if0lan.GetAddress (0));
  ns3helper::SetHostDefaultRoute(m_state.host1_ipv4, m_state.if1lan.GetAddress (1), m_state.if1lan.GetAddress (0));
  ns3helper::SetHostDefaultRoute(m_state.host2_ipv4, m_state.if2lan.GetAddress (1), m_state.if2lan.GetAddress (0));
}

void BgpMinimalScenario::ConfigureBgp (ns3::Time stopTime)
{
  ns3::Ptr<ns3::Bgp> bgp0 = ns3::CreateObject<ns3::Bgp> ();
  bgp0->SetAttribute ("RouterID", ns3::Ipv4AddressValue (m_state.if01.GetAddress (0)));
  bgp0->SetAttribute ("LibbgpLogLevel", ns3::EnumValue (libbgp::INFO));
  bgp0->AddRoute (
    ns3::Ipv4Address ("10.0.0.0"), ns3::Ipv4Mask ("/24"), m_state.if0lan.GetAddress (0));

  ns3::Peer peer0;
  peer0.peer_address = m_state.if01.GetAddress (1);
  peer0.peer_asn = 65001;
  peer0.local_asn = 65000;
  peer0.passive = false;
  bgp0->AddPeer (peer0);

  m_state.nodes.Get (0)->AddApplication (bgp0);
  bgp0->SetStartTime (ns3::Seconds (0));
  bgp0->SetStopTime (stopTime);

  ns3::Ptr<ns3::Bgp> bgp1 = ns3::CreateObject<ns3::Bgp> ();
  bgp1->SetAttribute ("RouterID", ns3::Ipv4AddressValue (m_state.if01.GetAddress (1)));
  bgp1->SetAttribute ("LibbgpLogLevel", ns3::EnumValue (libbgp::INFO));
  bgp1->AddRoute (
    ns3::Ipv4Address ("10.0.1.0"), ns3::Ipv4Mask ("/24"), m_state.if1lan.GetAddress (0));

  ns3::Peer peer_in_ext;
  peer_in_ext.peer_address = m_state.if01.GetAddress (0);
  peer_in_ext.peer_asn = 65000;
  peer_in_ext.local_asn = 65001;
  peer_in_ext.passive = false;
  bgp1->AddPeer (peer_in_ext);

  ns3::Peer peer_12_main;
  peer_12_main.peer_address = m_state.if12_main.GetAddress (1);
  peer_12_main.peer_asn = 65002;
  peer_12_main.local_asn = 65001;
  peer_12_main.passive = false;
  bgp1->AddPeer (peer_12_main);

  ns3::Peer peer_12_red;
  peer_12_red.peer_address = m_state.if12_red.GetAddress (1);
  peer_12_red.peer_asn = 65002;
  peer_12_red.local_asn = 65001;
  peer_12_red.passive = false;
  bgp1->AddPeer (peer_12_red);

  m_state.nodes.Get (1)->AddApplication (bgp1);
  bgp1->SetStartTime (ns3::Seconds (0));
  bgp1->SetStopTime (stopTime);

  ns3::Ptr<ns3::Bgp> bgp2 = ns3::CreateObject<ns3::Bgp> ();
  bgp2->SetAttribute ("RouterID", ns3::Ipv4AddressValue (m_state.if12_main.GetAddress (1)));
  bgp2->SetAttribute ("LibbgpLogLevel", ns3::EnumValue (libbgp::INFO));
  bgp2->AddRoute (
    ns3::Ipv4Address ("10.0.2.0"), ns3::Ipv4Mask ("/24"), m_state.if2lan.GetAddress (0));

  ns3::Peer peer2_main;
  peer2_main.peer_address = m_state.if12_main.GetAddress (0);
  peer2_main.peer_asn = 65001;
  peer2_main.local_asn = 65002;
  peer2_main.passive = false;
  bgp2->AddPeer (peer2_main);

  ns3::Peer peer2_red;
  peer2_red.peer_address = m_state.if12_red.GetAddress (0);
  peer2_red.peer_asn = 65001;
  peer2_red.local_asn = 65002;
  peer2_red.passive = false;
  bgp2->AddPeer (peer2_red);

  m_state.nodes.Get (2)->AddApplication (bgp2);
  bgp2->SetStartTime (ns3::Seconds (0));
  bgp2->SetStopTime (stopTime);
}

void BgpMinimalScenario::SetSwitchoverWindow (ns3::Time intentTime,
                                              ns3::Time activationTime,
                                              ns3::Time hardDeadline)
{
  m_switchoverIntentTime = intentTime;
  m_switchoverActivationTime = activationTime;
  m_switchoverHardDeadline = hardDeadline;
  m_hasValidSwitchoverWindow =
    (intentTime <= activationTime) && (activationTime < hardDeadline);

  std::ostringstream oss;
  oss << "SetSwitchoverWindow intent@" << intentTime.GetSeconds ()
      << "s activate@" << activationTime.GetSeconds ()
      << "s deadline@" << hardDeadline.GetSeconds () << "s";
  LogScenarioEvent ("SYSTEM", oss.str ());

  if (!m_hasValidSwitchoverWindow)
    {
      LogScenarioEvent ("SYSTEM",
                        "Invalid switchover timing window; expected intent <= activation < deadline");
    }
}

bool BgpMinimalScenario::HasValidSwitchoverWindow () const
{
  return m_hasValidSwitchoverWindow;
}

void BgpMinimalScenario::ScheduleLinkChange (LinkId currentLink,
                                             LinkId newLink,
                                             ns3::Time changeTime)
{
  std::ostringstream oss;
  oss << "ScheduleLinkChange " << LinkIdToString (currentLink) << "->"
      << LinkIdToString (newLink) << " @" << changeTime.GetSeconds () << "s";
  LogScenarioEvent ("SYSTEM", oss.str ());
  m_state.stage = BgpMinimalState::EventStage::SWITCHOVER_SCHEDULED;

  ns3::Simulator::Schedule (changeTime,
                            &BgpMinimalScenario::ChangeLink,
                            this,
                            currentLink,
                            newLink);
}

void BgpMinimalScenario::ChangeLink (LinkId currentLink, LinkId newLink)
{
  if (currentLink == newLink)
    {
      LogScenarioEvent ("SYSTEM", "ChangeLink ignored: current == new");
      return;
    }

  if (m_activeLink != currentLink)
    {
      std::ostringstream oss;
      oss << "ChangeLink ignored: active=" << LinkIdToString (m_activeLink)
          << " expectedCurrent=" << LinkIdToString (currentLink);
      LogScenarioEvent ("SYSTEM", oss.str ());
      return;
    }

  if ((newLink == LinkId::MAIN) && !m_mainPhysicalUp)
    {
      LogScenarioEvent ("SYSTEM",
                        "ChangeLink blocked: rollback conflict, main link is physically down");
      return;
    }
  if ((newLink == LinkId::REDUNDANT) && !m_redPhysicalUp)
    {
      LogScenarioEvent ("SYSTEM", "ChangeLink blocked: red link is physically down");
      return;
    }

  if (currentLink == LinkId::MAIN)
    {
      ns3helper::bringDownLink (m_state.nodes, m_state.if12_main, 1u, 2u);
    }
  else
    {
      ns3helper::bringDownLink (m_state.nodes, m_state.if12_red, 1u, 2u);
    }

  if (newLink == LinkId::MAIN)
    {
      ns3helper::bringUpLink (m_state.nodes, m_state.if12_main, 1u, 2u);
    }
  else
    {
      ns3helper::bringUpLink (m_state.nodes, m_state.if12_red, 1u, 2u);
    }

  m_activeLink = newLink;
  if (newLink == LinkId::REDUNDANT)
    {
      m_state.stage = BgpMinimalState::EventStage::SWITCHED_TO_RED;
    }
  else
    {
      m_state.stage = BgpMinimalState::EventStage::SWITCHED_BACK_TO_MAIN;
    }

  std::ostringstream oss;
  oss << "ChangeLink applied " << LinkIdToString (currentLink) << "->"
      << LinkIdToString (newLink) << " stage=" << StageToString (m_state.stage);
  LogScenarioEvent ("SYSTEM", oss.str ());

  if (!m_mainPhysicalUp && !m_redPhysicalUp)
    {
      LogScenarioEvent ("CHECK",
                        "No inter-domain links available after ChangeLink (both degraded)");
    }
}

void BgpMinimalScenario::BringDownMainLink ()
{
  if (m_activeLink != LinkId::REDUNDANT)
    {
      LogScenarioEvent ("CHECK",
                        "Deadline miss: redundant link not active at physical failure time");
    }
  else
    {
      LogScenarioEvent ("CHECK",
                        "Deadline met: redundant link active at physical failure time");
    }

  m_mainPhysicalUp = false;
  LogScenarioEvent ("SCENARIO", "BringDownMainLink (physical link-down)");
  ns3helper::bringDownLink (m_state.nodes, m_state.if12_main, 1u, 2u);
  m_state.stage = BgpMinimalState::EventStage::PHYSICAL_MAIN_DOWN;

  if ((m_activeLink == LinkId::MAIN) && m_redPhysicalUp)
    {
      ns3helper::bringUpLink (m_state.nodes, m_state.if12_red, 1u, 2u);
      m_activeLink = LinkId::REDUNDANT;
      LogScenarioEvent ("SCENARIO",
                        "Forced fallback to d12_red after physical d12_main failure");
    }

  if (!m_mainPhysicalUp && !m_redPhysicalUp)
    {
      LogScenarioEvent ("CHECK",
                        "No inter-domain links available after physical main-link down");
    }
}

void BgpMinimalScenario::BringUpMainLink ()
{
  m_mainPhysicalUp = true;
  LogScenarioEvent ("SCENARIO", "BringUpMainLink (physical link-repair)");
  if (m_activeLink == LinkId::MAIN)
    {
      ns3helper::bringUpLink (m_state.nodes, m_state.if12_main, 1u, 2u);
    }
  m_state.stage = BgpMinimalState::EventStage::PHYSICAL_MAIN_UP;

  {
    std::ostringstream oss;
    oss << "Main physical link up, stage=" << StageToString (m_state.stage);
    LogScenarioEvent ("SCENARIO", oss.str ());
  }
}

void BgpMinimalScenario::BringDownRedLink ()
{
  m_redPhysicalUp = false;
  LogScenarioEvent ("SCENARIO", "BringDownRedLink (physical link-down)");
  ns3helper::bringDownLink (m_state.nodes, m_state.if12_red, 1u, 2u);

  if (!m_mainPhysicalUp && !m_redPhysicalUp)
    {
      LogScenarioEvent ("CHECK",
                        "No inter-domain links available after physical red-link down");
    }
}

void BgpMinimalScenario::BringUpRedLink ()
{
  m_redPhysicalUp = true;
  LogScenarioEvent ("SCENARIO", "BringUpRedLink (physical link-repair)");
  if (m_activeLink == LinkId::REDUNDANT)
    {
      ns3helper::bringUpLink (m_state.nodes, m_state.if12_red, 1u, 2u);
    }
}

void BgpMinimalScenario::ScheduleEvents (ns3::Time failTime, ns3::Time repairTime)
{
  {
    std::ostringstream oss;
    oss << "ScheduleEvents fail@" << failTime.GetSeconds ()
        << "s repair@" << repairTime.GetSeconds () << "s";
    LogScenarioEvent ("SCHEDULER", oss.str ());
  }
  ns3::Simulator::Schedule (failTime, &BgpMinimalScenario::BringDownMainLink, this);
  ns3::Simulator::Schedule (repairTime, &BgpMinimalScenario::BringUpMainLink, this);
}

ns3::Ptr<ns3::Node> BgpMinimalScenario::GetPingSourceNode () const
{
  return m_state.nodes.Get (3);
}

ns3::Ipv4Address BgpMinimalScenario::GetPingDestinationAddress () const
{
  return m_state.if2lan.GetAddress (1);
}
