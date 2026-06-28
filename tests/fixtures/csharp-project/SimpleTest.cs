using NUnit.Framework;

namespace Tests
{
    public class SimpleTest
    {
        [Test]
        public void SimpleTestPasses()
        {
            Assert.AreEqual(2, 1 + 1);
        }
    }
}